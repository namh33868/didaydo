"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlignCenter,
  Bold,
  Check,
  Heading2,
  Heading3,
  ImagePlus,
  Italic,
  Link2,
  List,
  ListOrdered,
  Minus,
  Quote,
  Redo2,
  Strikethrough,
  Underline,
  Undo2,
  Unlink,
  X,
} from "lucide-react";

type Props = {
  initialHtml: string;
  onChange: (html: string) => void;
};

type ToolButtonProps = {
  label: string;
  onClick: () => void;
  children: ReactNode;
};

function ToolButton({ label, onClick, children }: ToolButtonProps) {
  return (
    <button
      className="rich-editor-tool"
      type="button"
      title={label}
      aria-label={label}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function escapeAttribute(value: string) {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function ArticleContentEditor({ initialHtml, onChange }: Props) {
  const editorRef = useRef<HTMLDivElement>(null);
  const savedRangeRef = useRef<Range | null>(null);
  const [imagePanelOpen, setImagePanelOpen] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [imageAlt, setImageAlt] = useState("");
  const [imageCaption, setImageCaption] = useState("");
  const [imageError, setImageError] = useState("");

  useEffect(() => {
    if (editorRef.current) editorRef.current.innerHTML = initialHtml || "";
    // Initial HTML is loaded when the editor is mounted. Updates are sent upward via onInput.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function rememberSelection() {
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    if (editor.contains(range.commonAncestorContainer)) savedRangeRef.current = range.cloneRange();
  }

  function restoreSelection() {
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection || !savedRangeRef.current) return;
    editor.focus();
    try {
      selection.removeAllRanges();
      selection.addRange(savedRangeRef.current);
    } catch {
      // If the saved selection no longer exists, the command will insert at the current caret.
    }
  }

  function publishHtml() {
    if (editorRef.current) onChange(editorRef.current.innerHTML);
  }

  function command(name: string, value?: string) {
    restoreSelection();
    document.execCommand(name, false, value);
    publishHtml();
    rememberSelection();
  }

  function insertLink() {
    rememberSelection();
    const url = window.prompt("Nhập URL liên kết (https://...):", "https://");
    if (!url) return;
    if (!/^https?:\/\//i.test(url) && !/^mailto:/i.test(url)) {
      window.alert("Vui lòng nhập URL bắt đầu bằng https://, http:// hoặc mailto:.");
      return;
    }
    command("createLink", url.trim());
  }

  function openImagePanel() {
    rememberSelection();
    setImageError("");
    setImagePanelOpen(true);
  }

  function insertImage() {
    const url = imageUrl.trim();
    if (!/^https:\/\//i.test(url)) {
      setImageError("Ảnh trong bài cần URL HTTPS để hiển thị an toàn.");
      return;
    }

    restoreSelection();
    const caption = imageCaption.trim();
    const figure = `<figure><img src="${escapeAttribute(url)}" alt="${escapeAttribute(imageAlt.trim())}" loading="lazy" />${caption ? `<figcaption>${escapeAttribute(caption)}</figcaption>` : ""}</figure><p><br></p>`;
    document.execCommand("insertHTML", false, figure);
    publishHtml();
    rememberSelection();
    setImageUrl("");
    setImageAlt("");
    setImageCaption("");
    setImagePanelOpen(false);
    setImageError("");
  }

  return (
    <div className="rich-editor">
      <div className="rich-editor-toolbar" role="toolbar" aria-label="Công cụ định dạng nội dung">
        <div className="rich-editor-tool-group">
          <ToolButton label="Hoàn tác" onClick={() => command("undo")}><Undo2 size={16} /></ToolButton>
          <ToolButton label="Làm lại" onClick={() => command("redo")}><Redo2 size={16} /></ToolButton>
        </div>
        <div className="rich-editor-tool-group">
          <ToolButton label="In đậm" onClick={() => command("bold")}><Bold size={16} /></ToolButton>
          <ToolButton label="In nghiêng" onClick={() => command("italic")}><Italic size={16} /></ToolButton>
          <ToolButton label="Gạch chân" onClick={() => command("underline")}><Underline size={16} /></ToolButton>
          <ToolButton label="Gạch ngang" onClick={() => command("strikeThrough")}><Strikethrough size={16} /></ToolButton>
        </div>
        <div className="rich-editor-tool-group">
          <ToolButton label="Tiêu đề cấp 2" onClick={() => command("formatBlock", "h2")}><Heading2 size={16} /></ToolButton>
          <ToolButton label="Tiêu đề cấp 3" onClick={() => command("formatBlock", "h3")}><Heading3 size={16} /></ToolButton>
          <ToolButton label="Trích dẫn" onClick={() => command("formatBlock", "blockquote")}><Quote size={16} /></ToolButton>
        </div>
        <div className="rich-editor-tool-group">
          <ToolButton label="Danh sách dấu chấm" onClick={() => command("insertUnorderedList")}><List size={16} /></ToolButton>
          <ToolButton label="Danh sách đánh số" onClick={() => command("insertOrderedList")}><ListOrdered size={16} /></ToolButton>
          <ToolButton label="Căn giữa" onClick={() => command("justifyCenter")}><AlignCenter size={16} /></ToolButton>
        </div>
        <div className="rich-editor-tool-group">
          <ToolButton label="Chèn liên kết" onClick={insertLink}><Link2 size={16} /></ToolButton>
          <ToolButton label="Bỏ liên kết" onClick={() => command("unlink")}><Unlink size={16} /></ToolButton>
          <ToolButton label="Chèn ảnh" onClick={openImagePanel}><ImagePlus size={16} /></ToolButton>
          <ToolButton label="Đường kẻ ngang" onClick={() => command("insertHorizontalRule")}><Minus size={16} /></ToolButton>
        </div>
      </div>

      {imagePanelOpen && (
        <div className="rich-image-panel">
          <div className="rich-image-panel-heading">
            <div><b>Chèn ảnh vào bài viết</b><small>Dùng URL ảnh HTTPS đang truy cập được.</small></div>
            <button type="button" className="rich-image-close" aria-label="Đóng chèn ảnh" onClick={() => setImagePanelOpen(false)}><X size={16} /></button>
          </div>
          <label className="rich-image-input"><span>URL ảnh *</span><input autoFocus value={imageUrl} onChange={(event) => setImageUrl(event.target.value)} placeholder="https://example.com/anh-du-lich.webp" /></label>
          <div className="rich-image-details">
            <label className="rich-image-input"><span>Mô tả ảnh (alt)</span><input value={imageAlt} onChange={(event) => setImageAlt(event.target.value)} placeholder="Mô tả ngắn gọn về ảnh" /></label>
            <label className="rich-image-input"><span>Chú thích ảnh (nếu có)</span><input value={imageCaption} onChange={(event) => setImageCaption(event.target.value)} placeholder="Ảnh: Tên tác giả / nguồn ảnh" /></label>
          </div>
          {imageError && <p className="rich-image-error" role="alert">{imageError}</p>}
          <div className="rich-image-actions">
            <button type="button" className="button-secondary" onClick={() => setImagePanelOpen(false)}>Hủy</button>
            <button type="button" className="button-primary" onClick={insertImage}><Check size={15} /> Chèn vào nội dung</button>
          </div>
        </div>
      )}

      <div
        ref={editorRef}
        className="rich-editor-canvas"
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-label="Nội dung bài viết"
        aria-multiline="true"
        spellCheck
        data-placeholder="Bắt đầu viết bài tại đây… Bôi đen đoạn chữ rồi chọn công cụ để định dạng."
        onInput={publishHtml}
        onKeyUp={rememberSelection}
        onMouseUp={rememberSelection}
        onBlur={rememberSelection}
      />
      <div className="rich-editor-status"><span>Trình soạn thảo trực quan</span><span>HTML được làm sạch trước khi lưu</span></div>
    </div>
  );
}
