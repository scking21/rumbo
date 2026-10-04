CREATE TABLE `deleted_projects` (
	`key` text PRIMARY KEY NOT NULL
);
--> statement-breakpoint
ALTER TABLE `artifacts` ADD `guard_written` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `projects` ADD `lifecycle` text DEFAULT 'active' NOT NULL;
--> statement-breakpoint
-- Drizzle does not model custom triggers. Keep this database-level invariant
-- when generating later migrations: older Worker code must not reuse a key.
CREATE TRIGGER `projects_reject_deleted_key`
BEFORE INSERT ON `projects`
FOR EACH ROW WHEN EXISTS (SELECT 1 FROM `deleted_projects` WHERE `key`=NEW.`key`)
BEGIN
 SELECT RAISE(ABORT, 'PROJECT_DELETED');
END;
