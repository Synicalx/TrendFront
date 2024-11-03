# TrendFront
Basic reddit trend analysis from the front page

## Setup

Venv would be nice;
```bash
python3 -m venv venv

source venv/bin/activate
```

Setup ENV vars;

```
REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET
SUPABASE_URL
SUPABASE_KEY
```

## Supabase setup

Once off, very easy to do;

1. Make a project
2. Sort out keys, URL etc
3. Run this to set up the table

```sql
CREATE TABLE posts (
    post_id TEXT PRIMARY KEY,
    title TEXT,
    linked_page_title TEXT,
    upvotes INTEGER,
    comments_count INTEGER,
    timestamp TEXT,
    fetch_time TEXT,
    score REAL
);
```