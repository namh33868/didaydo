import { NextResponse } from "next/server";
import { getAdminSession, permissionsForRole } from "@/lib/auth";

export async function GET() {
  const session = await getAdminSession();
  if (!session) return NextResponse.json({ authenticated: false }, { status: 401 });
  return NextResponse.json({
    authenticated: true,
    email: session.email,
    fullName: session.fullName,
    role: session.role,
    userId: session.userId,
    permissions: permissionsForRole(session.role),
  });
}
