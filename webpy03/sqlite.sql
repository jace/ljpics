CREATE TABLE IF NOT EXISTS userpics (
    username TEXT PRIMARY KEY,
    name TEXT,
    image TEXT,
    blocked BOOL NOT NULL DEFAULT False,
    refreshdate INTEGER NOT NULL
    );

