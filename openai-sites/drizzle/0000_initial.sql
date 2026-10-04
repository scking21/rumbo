CREATE TABLE `artifacts` (
	`project_key` text NOT NULL,
	`digest` text NOT NULL,
	`size` integer NOT NULL,
	PRIMARY KEY(`project_key`, `digest`),
	FOREIGN KEY (`project_key`) REFERENCES `projects`(`key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `browser_sessions` (
	`id_hash` text PRIMARY KEY NOT NULL,
	`subject` text NOT NULL,
	`csrf_hash` text NOT NULL,
	`expires_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `events` (
	`project_key` text NOT NULL,
	`seq` integer NOT NULL,
	`payload` text NOT NULL,
	`previous` text NOT NULL,
	`digest` text NOT NULL,
	PRIMARY KEY(`project_key`, `seq`),
	FOREIGN KEY (`project_key`) REFERENCES `projects`(`key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `memberships` (
	`project_key` text NOT NULL,
	`subject` text NOT NULL,
	`role` text NOT NULL,
	PRIMARY KEY(`project_key`, `subject`),
	FOREIGN KEY (`project_key`) REFERENCES `projects`(`key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `projects` (
	`key` text PRIMARY KEY NOT NULL,
	`alias` text NOT NULL,
	`owner_subject` text NOT NULL,
	`owner_actor` text NOT NULL,
	`head_seq` integer DEFAULT 0 NOT NULL,
	`head_digest` text DEFAULT '0000000000000000000000000000000000000000000000000000000000000000' NOT NULL,
	`event_bytes` integer DEFAULT 0 NOT NULL,
	`created_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `workers` (
	`id` text PRIMARY KEY NOT NULL,
	`project_key` text NOT NULL,
	`subject` text NOT NULL,
	`actor` text NOT NULL,
	`label` text NOT NULL,
	`expires_at` integer NOT NULL,
	FOREIGN KEY (`project_key`) REFERENCES `projects`(`key`) ON UPDATE no action ON DELETE no action
);
