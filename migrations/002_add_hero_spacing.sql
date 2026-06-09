-- Migration: add hero_spacing_ms column to war_config
ALTER TABLE war_config ADD COLUMN hero_spacing_ms INTEGER NOT NULL DEFAULT 0;