#!/usr/bin/env python

import os.path
from base64 import b64decode
import ConfigParser
from StringIO import StringIO
import xml.dom.minidom as minidom
from xml.parsers.expat import ExpatError
import urllib
from urllib2 import urlparse
import simplejson
import re
import time
import web

DEFAULT_USERPIC = 'http://l-stat.livejournal.com/img/profile_icons/user.gif'
REFRESH_TIMEOUT = 604800 # 1 week (60s*60m*24h*7d)

render = web.template.render('templates/')

config = ConfigParser.ConfigParser()
config.read(['.ljpics.conf', os.path.expanduser('~/.ljpics.conf'),
             '/etc/ljpics.conf'])

db_parameters = {}
for key, value in config.items('ljpics'):
    db_parameters[key] = value

db = web.database(**db_parameters)


urls = (
    '/', 'Index',
    '/url/(.*)', 'LinkUserImage',
    '/geturl', 'GetLinkUserImage',
    '/img/(.*)', 'UserImage',
    '/json/(.*)', 'UserData',
    '/jsonurl/(.*)', 'LinkUserData',
    '/getjsonurl', 'GetLinkUserData',
    '/refresh/(.*)', 'UserRefresh',
    '/info/(.*)', 'UserInfo',
    )


def check(validator, value):
    return not validator(lambda x, y: False)(None, value) and True or False


def is_valid_lj_user(method):
    """
    Validates LiveJournal username.

    >>> check(is_valid_lj_user, 'jace')
    True
    >>> check(is_valid_lj_user, 'Jace')
    False
    >>> check(is_valid_lj_user, '__hi__')
    True
    >>> check(is_valid_lj_user, 'hi-there')
    False
    >>> check(is_valid_lj_user, '9inch')
    True
    >>> check(is_valid_lj_user, 'jace.livejournal.com')
    False
    >>> check(is_valid_lj_user, '')
    False
    """
    def validator(self, username):
        if not username or re.search('[^a-z0-9_]', username):
            return u'"%s" is not a valid LiveJournal user name.' % username
        return method(self, username)
    return validator


def get_username_from_url(ljurl):
    """
    Return a username given a LiveJournal URL.

    >>> get_username_from_url('http://jace.livejournal.com/')
    'jace'
    >>> get_username_from_url('http://jace.livejournal.com/profile')
    'jace'
    >>> get_username_from_url('jace.livejournal.com')
    'jace'
    >>> get_username_from_url('hi-there.livejournal.com')
    'hi_there'
    >>> get_username_from_url('http://users.livejournal.com/__init__')
    '__init__'
    >>> get_username_from_url('http://jace.vox.com/')
    ''
    >>> get_username_from_url('http://www.livejournal.com/img/userinfo.gif')
    ''
    """
    parts = urlparse.urlsplit(ljurl)
    domain = parts.netloc
    path = parts.path
    if parts.scheme == '' and parts.netloc == '':
        domain = path.split('/')[0]
        if '/' in path:
            path = '/'.join(path.split('/')[1:])
        else:
            path = ''
    if domain in ['users.livejournal.com', 'community.livejournal.com']:
        username = path.split('/')[1] # Path starts with /, so skip [0]
    elif domain == 'www.livejournal.com':
        username = ''
    elif not domain.endswith('.livejournal.com'):
        username = ''
    else:
        username = domain.split('.')[0]
    return username.replace('-', '_')

def userlink(username):
    """
    Return a link to a user's journal given their username.

    >>> userlink('jace')
    'http://jace.livejournal.com/'
    >>> userlink('hi_there')
    'http://hi-there.livejournal.com/'
    >>> userlink('__init__')
    'http://users.livejournal.com/__init__/'
    """
    if username.startswith('_') or username.endswith('_'):
        return 'http://users.livejournal.com/%s/' % username
    else:
        return 'http://%s.livejournal.com/' % username.replace('_', '-')


def profilelink(username):
    """
    Return a link to the user profile given a username.

    >>> profilelink('jace')
    'http://jace.livejournal.com/profile'
    """
    return userlink(username) + 'profile'


def foaflink(username):
    """
    Return link to FOAF file for user. Doesn't check if username is valid.

    >>> foaflink('jace')
    'http://jace.livejournal.com/data/foaf'
    >>> foaflink('hi_there')
    'http://hi-there.livejournal.com/data/foaf'
    >>> foaflink('__init__')
    'http://users.livejournal.com/__init__/data/foaf'
    """
    return userlink(username) + 'data/foaf'


def get_images(url):
    """
    Based on code by Chris Schmidt, originally described at
    http://crschmidt.net/blog/categories/semantic-web/foaf/
    """

    foaf_url = url

    foaf = "http://xmlns.com/foaf/0.1/"                  # FOAF Namespace
    rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"  # RDF Namespace

    u = urllib.urlopen(foaf_url)                         # Load file
    doc = minidom.parseString(u.read())                  # XML Parse
    u.close()                                            # Close file

    # Search through all foaf:PersonalProfileDocuments, looking for one
    # which is about this doc (rdf:about="") and which has a maker element

    ppds = doc.getElementsByTagNameNS(foaf, "PersonalProfileDocument")
    ppd = None
    for i in ppds:
        if (i.getAttributeNodeNS(rdf, "about").value==u''):
            ppd = i
            break

    target = None
    if ppd:
        maker = ppd.getElementsByTagNameNS(foaf,"maker")[0]
        if maker:
            type, value = maker.attributes.items()[0]

        people = doc.getElementsByTagNameNS(foaf, "Person")

        for i in people:
            try:
                if ("nodeID" in type):
                    # rdf:nodeID="nodename"
                    if (i.getAttributeNode(type).value == value):
                        target = i
                        break
                if ("resource" in type):
                    # rdf:resource="#nodename", rdf:ID="nodename"
                    if (value[1:] == i.getAttributeNodeNS(rdf,"ID").value):
                        target = i
                        break
                    if (value == i.getAttributeNodeNS(rdf,"resource").value):
                        target = i
                        break
            except Exception, E:
                pass
    if not target:
        people = doc.getElementsByTagNameNS(foaf, "Person")


    result = {}
    for target in people:
        person = {}

        # Create a dict of common variables needed.
        for i in ["nick", "name", "image", "member_name"]:
            elements = target.getElementsByTagNameNS(foaf,i)
            if (len(elements) > 0 and elements[0].parentNode == target):
                if elements[0].firstChild is not None:
                    person[i] = elements[0].firstChild.nodeValue
        for i in ["img"]:
            elements = target.getElementsByTagNameNS(foaf,i)
            if (len(elements) > 0 and elements[0].parentNode == target):
                person[i] = elements[0].getAttributeNodeNS(rdf,"resource").value
        if 'img' in person:
            person['image'] = person['img']
            del person['img']
        if 'member_name' in person:
            person['name'] = person['member_name']
            del person['member_name']
        if 'nick' in person:
            #result.get(person['nick'], {}).update(person)
            result[person['nick']] = person
    return result


def get_or_refresh_userdata(username):
    userdata = list(db.select('userpics', locals(),
                               where='username = $username'))
    if len(userdata) == 0:
        userdata = UserRefresh().refresh(username)
    else:
        userdata = userdata[0]
        if int(time.time()) - userdata.refreshdate >= REFRESH_TIMEOUT:
            userdata = UserRefresh().refresh(username)
    return userdata


class Index:
    """
    LJPics Index Page
    """
    def GET(self):
        count = db.select('userpics', what='count(*) as count')[0].count
        return render.index(count=count)


class LinkUserImage:
    """
    Retrieve userpic given a LiveJournal URL
    """
    def GET(self, url):
        return UserImage().GET(get_username_from_url(url))


class GetLinkUserImage:
    """
    Retrieve userpic using a GET parameter.
    """
    def GET(self):
        url = web.input('url').url
        return UserImage().GET(get_username_from_url(url))


class LinkUserData:
    """
    Retrieve user data given a LiveJournal URL
    """
    def GET(self, url):
        return UserData().GET(get_username_from_url(url))


class GetLinkUserData:
    """
    Retrieve user data using a GET parameter.
    """
    def GET(self):
        url = web.input('url').url
        return UserData().GET(get_username_from_url(url))


class UserInfo:
    """
    Display page with information.
    """
    @is_valid_lj_user
    def GET(self, username):
        userdata = get_or_refresh_userdata(username)
        if not userdata or not userdata.image or userdata.blocked in [True, 1, 'True']:
            return "Unavailable."
        else:
            return render.userinfo(username, userdata.name, userdata.image,
                                   userlink(username), profilelink(username))


class UserImage:
    """
    Redirect to user image on LiveJournal
    """
    @is_valid_lj_user
    def GET(self, username):
        userdata = get_or_refresh_userdata(username)
        if not userdata or not userdata.image or userdata.blocked in [True, 1, 'True']:
            image = DEFAULT_USERPIC
        else:
            image = userdata.image
        raise web.redirect(image, status='302 Found')

class UserRefresh:
    """
    Refresh user image from LiveJournal.
    """
    @is_valid_lj_user
    def GET(self, username):
        userdata = list(db.select('userpics', locals(),
                                   where='username = $username'))
        if len(userdata) > 0 and userdata[0].blocked in [1, True, 'True']:
            return "Blocked."
        try:
            userdata = self.refresh(username)
        except IOError:
            return "Failed."
        if userdata is None:
            return "Failed."
        return "Refreshed."

    @is_valid_lj_user
    def refresh(self, username):
        # Assume not blocked, since this is not a user facing method.
        try:
            data = get_images(foaflink(username))
        except ExpatError:
            # Got garbage. Possibly a 404. Cache for refresh period
            if db.select('userpics', locals(), what='count(*) as count',
                         where='username = $username')[0].count > 0:
                db.update('userpics', 'username = $username', locals(),
                          blocked = False, refreshdate = int(time.time()))
            else:
                db.insert('userpics', username=username,
                          blocked=False, refreshdate = int(time.time()))
            return None
        for nick, person in data.items():
            savedata = {
                    'username': nick,
                    'name': person.get('name', u''),
                    'image': person.get('image', u''),
                    'refreshdate': int(time.time())
                    }
            if db.select('userpics', locals(), what='count(*) as count',
                          where='username = $nick')[0].count > 0:
                db.update('userpics', 'username = $nick', locals(),
                          **savedata)
            else:
                db.insert('userpics', **savedata)
        userdata = list(db.select('userpics', locals(),
                                   where='username = $username'))
        if len(userdata) == 0:
            return None
        else:
            return userdata[0]


class UserData:
    """
    Return user data as JSON.
    """
    def GET(self, username):
        jsonp = web.input(jsonp=None).jsonp
        if jsonp:
            wrapper = jsonp+'(%s)'
        else:
            wrapper = '%s'
        web.header('Content-Type', 'application/json')
        userdata = get_or_refresh_userdata(username)
        if not userdata:
            return wrapper % simplejson.dumps(None)
        else:
            if userdata.blocked in [True, 1, 'True']:
                return wrapper % simplejson.dumps(None)
            elif userdata.name == '' and userdata.image == '':
                return wrapper % simplejson.dumps(None)
            else:
                return wrapper % simplejson.dumps({
                    'username': userdata.username,
                    'name': userdata.name,
                    'image': userdata.image,
                    'refreshdate': userdata.refreshdate,
                    })

##web.webapi.internalerror = web.debugerror

app = web.application(urls, globals())
application = app.wsgifunc()

if __name__ == '__main__':
    import sys
    if '-t' in sys.argv:
        import doctest
        doctest.testmod()
    else:
        app.run()
