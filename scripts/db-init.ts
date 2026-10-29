import "dotenv/config";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import postgres from "postgres";

async function main() {
  if (!process.env.DATABASE_URL) throw new Error("Missing DATABASE_URL. Copy .env.example to .env first.");
  const db = postgres(process.env.DATABASE_URL, { max: 1, prepare: false });
  try {
    const content = await readFile(resolve(process.cwd(), "db/schema.sql"), "utf8");
    const statements = content.split(";").map((statement) => statement.trim()).filter(Boolean);
    for (const statement of statements) await db.unsafe(statement);
    console.log(`Database schema initialized (${statements.length} statements).`);
  } finally {
    await db.end();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
