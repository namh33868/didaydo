"use client";

import { useEffect, useState } from "react";
import { GoogleAnalytics } from "@/components/GoogleAnalytics";

type AnalyticsChoice = "granted" | "denied";

const CONSENT_KEY = "didaydo-analytics-consent-v1";
const OPEN_EVENT = "didaydo:open-analytics-consent";

export function AnalyticsConsent() {
  const [choice, setChoice] = useState<AnalyticsChoice | null>(null);
  const [ready, setReady] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(CONSENT_KEY);
      if (saved === "granted" || saved === "denied") {
        setChoice(saved);
      } else {
        setShowPrompt(true);
      }
    } catch {
      setShowPrompt(true);
    }
    setReady(true);

    const openPrompt = () => {
      try {
        window.localStorage.removeItem(CONSENT_KEY);
      } catch {
        // The prompt remains available even when storage is blocked.
      }
      setChoice(null);
      setShowPrompt(true);
    };
    window.addEventListener(OPEN_EVENT, openPrompt);
    return () => window.removeEventListener(OPEN_EVENT, openPrompt);
  }, []);

  function choose(value: AnalyticsChoice) {
    try {
      window.localStorage.setItem(CONSENT_KEY, value);
    } catch {
      // Consent still applies for this page view if storage is blocked.
    }
    setChoice(value);
    setShowPrompt(false);
  }

  return (
    <>
      {choice === "granted" && <GoogleAnalytics />}
      {ready && showPrompt && (
        <aside className="analytics-consent-banner" role="dialog" aria-label="Lựa chọn cookie phân tích">
          <div className="analytics-consent-copy">
            <strong>Cho phép đo lường lượt truy cập?</strong>
            <p>Cookie phân tích giúp Đi Đây Đó hiểu những trang được quan tâm, số phiên truy cập và tần suất độc giả quay lại. Không đồng ý không ảnh hưởng đến việc đọc bài.</p>
            <a href="/chinh-sach-bao-mat">Đọc chính sách bảo mật</a>
          </div>
          <div className="analytics-consent-actions">
            <button type="button" className="analytics-consent-decline" onClick={() => choose("denied")}>Không đồng ý</button>
            <button type="button" className="analytics-consent-accept" onClick={() => choose("granted")}>Đồng ý</button>
          </div>
        </aside>
      )}
    </>
  );
}

export function AnalyticsConsentSettings() {
  return (
    <button
      type="button"
      className="analytics-consent-settings"
      onClick={() => window.dispatchEvent(new Event(OPEN_EVENT))}
    >
      Thay đổi lựa chọn cookie phân tích
    </button>
  );
}
