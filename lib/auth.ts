import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";
import { db } from "@/lib/db";

const COOKIE_NAME = "didaydo_admin";
const SESSION_TTL = 60 * 60 * 12;

export type AdminRole = "admin" | "editor" | "author" | "viewer";
export type AdminPermission = "posts:view" | "posts:create" | "posts:edit:any" | "posts:edit:own" | "posts:publish" | "posts:delete" | "ingest:view" | "users:manage";
export type AdminSession = {
  email: string;
  fullName: string;
  role: AdminRole;
  userId: string | null;
};

const ROLE_PERMISSIONS: Record<AdminRole, AdminPermission[]> = {
  admin: ["posts:view", "posts:create", "posts:edit:any", "posts:edit:own", "posts:publish", "posts:delete", "ingest:view", "users:manage"],
  editor: ["posts:view", "posts:create", "posts:edit:any", "posts:edit:own", "posts:publish", "posts:delete", "ingest:view"],
  author: ["posts:view", "posts:create", "posts:edit:own"],
  viewer: ["posts:view"],
};

export function isAdminRole(value: unknown): value is AdminRole {
  return value === "admin" || value === "editor" || value === "author" || value === "viewer";
}

export function permissionsForRole(role: AdminRole): AdminPermission[] {
  return [...ROLE_PERMISSIONS[role]];
}

export function hasPermission(role: AdminRole, permission: AdminPermission): boolean {
  return ROLE_PERMISSIONS[role].includes(permission);
}

function signingKey() {
  const secret = process.env.SESSION_SECRET;
  if (!secret || secret.length < 32) throw new Error("SESSION_SECRET must be at least 32 characters long.");
  return new TextEncoder().encode(secret);
}

export async function createAdminSession(email: string, role: AdminRole = "admin", userId: string | null = null, fullName = "Quản trị viên") {
  const token = await new SignJWT({ role, email, userId: userId || undefined, fullName })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${SESSION_TTL}s`)
    .sign(signingKey());
  const store = await cookies();
  store.set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_TTL,
  });
}

export async function getAdminSession(): Promise<AdminSession | null> {
  const store = await cookies();
  const token = store.get(COOKIE_NAME)?.value;
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, signingKey());
    if (!isAdminRole(payload.role) || typeof payload.email !== "string") return null;

    // Sessions for database-managed accounts are checked on every request so role changes
    // and account deactivation take effect immediately rather than after the token expires.
    if (typeof payload.userId === "string") {
      const rows = await db<{ id: string; email: string; full_name: string; role: string; active: boolean }[]>`
        SELECT id, email, full_name, role, active FROM admin_users WHERE id = ${payload.userId} LIMIT 1
      `;
      const user = rows[0];
      if (!user || !user.active || !isAdminRole(user.role)) return null;
      return { userId: user.id, email: user.email, fullName: user.full_name, role: user.role };
    }

    // Backwards compatibility for the root administrator configured in .env and sessions
    // created before database accounts were introduced.
    if (payload.role !== "admin") return null;
    return {
      email: payload.email,
      fullName: typeof payload.fullName === "string" ? payload.fullName : "Quản trị viên",
      role: "admin",
      userId: null,
    };
  } catch {
    return null;
  }
}

/** Kept for compatibility with existing server components. It now means authenticated CMS account. */
export async function requireAdmin() {
  return getAdminSession();
}

export async function clearAdminSession() {
  const store = await cookies();
  store.set(COOKIE_NAME, "", { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: 0 });
}
