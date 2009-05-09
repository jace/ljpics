CREATE TABLE IF NOT EXISTS userpics (
    username TEXT PRIMARY KEY,
    name TEXT,
    image TEXT,
    blocked BOOLEAN NOT NULL DEFAULT f,
    refreshdate INTEGER NOT NULL
    );

