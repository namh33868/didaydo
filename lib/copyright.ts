import { db } from "@/lib/db";

let setupPromise: Promise<void> | null = null;

export async function ensureCopyrightTables() {
  if (!setupPromise) {
    setupPromise = (async () => {
      await db`
        CREATE TABLE IF NOT EXISTS copyright_reports (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          claimant_name TEXT NOT NULL,
          claimant_email TEXT NOT NULL,
          relationship TEXT NOT NULL CHECK (relationship IN ('owner', 'authorized_agent', 'other')),
          work_title TEXT NOT NULL DEFAULT '',
          original_work_url TEXT NOT NULL DEFAULT '',
          reported_url TEXT NOT NULL,
          details TEXT NOT NULL,
          declaration BOOLEAN NOT NULL DEFAULT FALSE,
          status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'reviewing', 'resolved', 'rejected')),
          review_note TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          reviewed_at TIMESTAMPTZ
        )
      `;
      await db`CREATE INDEX IF NOT EXISTS copyright_reports_status_created_idx ON copyright_reports (status, created_at DESC)`;
      await db`
        CREATE TABLE IF NOT EXISTS copyright_report_rate_limits (
          ip_hash TEXT PRIMARY KEY,
          window_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          request_count INTEGER NOT NULL DEFAULT 0
        )
      `;
    })();
  }
  try {
    await setupPromise;
  } catch (error) {
    setupPromise = null;
    throw error;
  }
}
