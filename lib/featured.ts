import { db } from "@/lib/db";

let schemaPromise: Promise<void> | null = null;
let lastExpirySweep = 0;

/**
 * Adds the expiry column without requiring a separate manual database migration.
 * Existing manually featured stories receive one final 7-day window after rollout.
 */
export async function ensureFeaturedSchedule() {
  if (!schemaPromise) {
    schemaPromise = (async () => {
      await db`ALTER TABLE posts ADD COLUMN IF NOT EXISTS featured_until TIMESTAMPTZ`;
      await db`
        UPDATE posts
        SET featured_until = NOW() + INTERVAL '7 days'
        WHERE featured = TRUE AND featured_until IS NULL
      `;
      await db`
        CREATE INDEX IF NOT EXISTS posts_featured_until_idx
        ON posts (featured, featured_until DESC)
      `;
    })().catch((error) => {
      schemaPromise = null;
      throw error;
    });
  }

  await schemaPromise;

  // Sweep expired flags at most once per minute per server instance.
  const now = Date.now();
  if (now - lastExpirySweep >= 60_000) {
    lastExpirySweep = now;
    try {
      await db`
        UPDATE posts
        SET featured = FALSE, featured_until = NULL, updated_at = NOW()
        WHERE featured = TRUE
          AND featured_until IS NOT NULL
          AND featured_until <= NOW()
      `;
    } catch (error) {
      lastExpirySweep = 0;
      throw error;
    }
  }
}