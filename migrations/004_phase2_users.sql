-- Migration 004: Phase 2 — Multi-user foundation
-- Users, Packages, Orders, extend existing tables

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id TEXT NOT NULL UNIQUE,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    balance_war INTEGER DEFAULT 0,
    total_wars INTEGER DEFAULT 0,
    total_tickets INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    is_suspended BOOLEAN DEFAULT 0,
    is_admin BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    war_count INTEGER NOT NULL,
    price_idr INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    package_id INTEGER REFERENCES packages(id),
    order_ref TEXT NOT NULL UNIQUE,
    amount_idr INTEGER NOT NULL,
    war_count INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    payment_url TEXT,
    paid_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Extend existing tables (SQLite ALTER TABLE is limited, use defaults)
ALTER TABLE war_config ADD COLUMN user_id INTEGER REFERENCES users(id);
ALTER TABLE war_history ADD COLUMN user_id INTEGER REFERENCES users(id);
ALTER TABLE war_history ADD COLUMN order_id INTEGER REFERENCES orders(id);
ALTER TABLE cookies ADD COLUMN user_id INTEGER REFERENCES users(id);

-- Backfill: set user_id for existing records (admin = telegram_id 690744680)
INSERT OR IGNORE INTO users (telegram_id, username, first_name, is_admin)
VALUES ('690744680', 'kr2k3n', 'Eko', 1);

UPDATE war_config SET user_id = (SELECT id FROM users WHERE telegram_id = '690744680')
WHERE owner_chat_id = '690744680' AND user_id IS NULL;

UPDATE war_history SET user_id = (SELECT id FROM users WHERE telegram_id = '690744680')
WHERE user_id IS NULL;

UPDATE cookies SET user_id = (SELECT id FROM users WHERE telegram_id = '690744680')
WHERE owner_chat_id = '690744680' AND user_id IS NULL;

-- Seed default packages
INSERT OR IGNORE INTO packages (name, war_count, price_idr) VALUES
    ('Bronze — 5 War', 5, 25000),
    ('Silver — 10 War', 10, 40000),
    ('Gold — 20 War', 20, 70000),
    ('Platinum — 50 War', 50, 150000);