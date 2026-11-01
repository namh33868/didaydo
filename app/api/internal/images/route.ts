import { timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";
import { list, put } from "@vercel/blob";

export const runtime = "nodejs";

const MAX_IMAGE_BYTES = 512 * 1024;
const IMAGE_PREFIX = "images/covers/";

function isAuthorized(request: Request): boolean {
  const expected = process.env.INGEST_API_KEY;
  if (!expected || expected.length < 24) return false;

  const authorization = request.headers.get("authorization") || "";
  const supplied = authorization.startsWith("Bearer ")
    ? authorization.slice("Bearer ".length)
    : "";

  if (!supplied) return false;
  const expectedBytes = Buffer.from(expected);
  const suppliedBytes = Buffer.from(supplied);
  return expectedBytes.length === suppliedBytes.length
    && timingSafeEqual(expectedBytes, suppliedBytes);
}

function jsonError(error: string, status: number) {
  return NextResponse.json({ ok: false, error }, { status });
}

function isWebp(buffer: Buffer): boolean {
  return buffer.length >= 12
    && buffer.subarray(0, 4).toString("ascii") === "RIFF"
    && buffer.subarray(8, 12).toString("ascii") === "WEBP";
}

export async function GET(request: Request) {
  if (!isAuthorized(request)) {
    return jsonError("Không có quyền truy cập.", 401);
  }

  try {
    const result = await list({ prefix: IMAGE_PREFIX, limit: 1 });
    return NextResponse.json({
      ok: true,
      storage: "vercel-blob",
      prefix: IMAGE_PREFIX,
      checked: result.blobs.length,
    });
  } catch (error) {
    console.error("[blob-image-api] storage preflight failed", {
      errorType: error instanceof Error ? error.name : "UnknownError",
    });
    return jsonError("Vercel Blob chưa sẵn sàng hoặc chưa được kết nối với project.", 503);
  }
}

export async function POST(request: Request) {
  if (!isAuthorized(request)) {
    return jsonError("Không có quyền truy cập.", 401);
  }

  const contentType = (request.headers.get("content-type") || "")
    .split(";", 1)[0]
    .trim()
    .toLowerCase();
  if (contentType !== "image/webp") {
    return jsonError("Chỉ chấp nhận ảnh WebP.", 415);
  }

  const filename = (request.headers.get("x-image-filename") || "").trim();
  if (!/^[a-z0-9][a-z0-9-]{0,89}-[a-f0-9]{12}\.webp$/.test(filename)) {
    return jsonError("Tên file ảnh không hợp lệ.", 400);
  }

  const declaredLength = Number(request.headers.get("content-length") || 0);
  if (declaredLength > MAX_IMAGE_BYTES) {
    return jsonError("Ảnh vượt giới hạn 512 KB.", 413);
  }

  let bytes: Buffer;
  try {
    bytes = Buffer.from(await request.arrayBuffer());
  } catch {
    return jsonError("Không đọc được dữ liệu ảnh.", 400);
  }

  if (bytes.length === 0) {
    return jsonError("Dữ liệu ảnh rỗng.", 400);
  }
  if (bytes.length > MAX_IMAGE_BYTES) {
    return jsonError("Ảnh vượt giới hạn 512 KB.", 413);
  }
  if (!isWebp(bytes)) {
    return jsonError("Dữ liệu tải lên không phải ảnh WebP hợp lệ.", 415);
  }

  try {
    const uploaded = await put(IMAGE_PREFIX + filename, bytes, {
      access: "public",
      addRandomSuffix: false,
      allowOverwrite: true,
      contentType: "image/webp",
      cacheControlMaxAge: 31_536_000,
    });

    return NextResponse.json({
      ok: true,
      url: uploaded.url,
      pathname: uploaded.pathname,
      bytes: bytes.length,
    });
  } catch (error) {
    console.error("[blob-image-api] upload failed", {
      filename,
      bytes: bytes.length,
      errorType: error instanceof Error ? error.name : "UnknownError",
    });
    return jsonError("Không thể lưu ảnh vào Vercel Blob.", 502);
  }
}
