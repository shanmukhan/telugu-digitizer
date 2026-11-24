import { useId, useState, type DragEvent, type FormEvent } from "react";

interface BookUploadFormProps {
  busy: boolean;
  onUpload: (formData: FormData) => Promise<void>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(2)} MB`;
}

export function BookUploadForm({ busy, onUpload }: BookUploadFormProps) {
  const headingId = useId();
  const fileId = useId();
  const titleId = useId();
  const authorId = useId();
  const orthoId = useId();
  const consentId = useId();
  const fileHelpId = useId();

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [orthographyProfile, setOrthographyProfile] = useState("unspecified");
  const [trainingConsent, setTrainingConsent] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  function applyChosenFile(file: File | null) {
    setSelectedFile(file);
    setLocalError(null);
    if (file && !title.trim()) {
      setTitle(file.name.replace(/\.pdf$/i, ""));
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const dropped = event.dataTransfer.files?.[0] ?? null;
    if (!dropped) return;
    if (dropped.type !== "application/pdf" && !dropped.name.toLowerCase().endsWith(".pdf")) {
      setLocalError("Please drop a valid PDF file (.pdf).");
      return;
    }
    applyChosenFile(dropped);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) {
      setLocalError("Please choose a PDF file to upload.");
      return;
    }
    if (!title.trim()) {
      setLocalError("Please enter a book title.");
      return;
    }
    setLocalError(null);
    const data = new FormData();
    data.append("file", selectedFile);
    data.append("title", title.trim());
    if (author.trim()) {
      data.append("author", author.trim());
    }
    data.append("orthography_profile", orthographyProfile);
    data.append("training_consent", String(trainingConsent));

    await onUpload(data);
    setSelectedFile(null);
    setTitle("");
    setAuthor("");
    setTrainingConsent(false);
    event.currentTarget.reset();
  }

  return (
    <section className="panel-card" aria-labelledby={headingId}>
      <h2 id={headingId}>Upload Printed Telugu PDF</h2>
      <form aria-labelledby={headingId} onSubmit={handleSubmit}>
        <div className="form-field">
          <label htmlFor={fileId}>
            PDF file <span aria-hidden="true">*</span>
          </label>
          <div
            className={`file-dropzone${dragActive ? " drag-active" : ""}${selectedFile ? " has-file" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
          >
            <input
              id={fileId}
              name="file"
              type="file"
              accept="application/pdf,.pdf"
              aria-describedby={fileHelpId}
              required={!selectedFile}
              onChange={(e) => {
                const file = e.target.files?.[0] ?? null;
                applyChosenFile(file);
              }}
            />
            {selectedFile ? (
              <div className="file-dropzone-meta">
                <span className="badge ok">✓ {selectedFile.name}</span>
                <span className="hint-text">{formatBytes(selectedFile.size)}</span>
              </div>
            ) : (
              <span className="hint-text">Drag &amp; drop a Telugu PDF here, or click to browse</span>
            )}
          </div>
          <span id={fileHelpId} className="hint-text">
            Stored locally read-only with SHA-256 deduplication.
          </span>
        </div>

        <div className="form-field">
          <label htmlFor={titleId}>
            Book title <span aria-hidden="true">*</span>
          </label>
          <input
            id={titleId}
            name="title"
            type="text"
            required
            value={title}
            onChange={(e) => {
              setTitle(e.target.value);
              setLocalError(null);
            }}
          />
        </div>

        <div className="form-field">
          <label htmlFor={authorId}>Author (optional)</label>
          <input
            id={authorId}
            name="author"
            type="text"
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
          />
        </div>

        <div className="form-field">
          <label htmlFor={orthoId}>Orthography profile</label>
          <select
            id={orthoId}
            name="orthography_profile"
            value={orthographyProfile}
            onChange={(e) => setOrthographyProfile(e.target.value)}
          >
            <option value="unspecified">Unspecified</option>
            <option value="modern_standard">Modern standard Telugu</option>
            <option value="classical_literary">Classical / literary Telugu</option>
            <option value="pre_1950_print">Pre-1950 print conventions</option>
          </select>
        </div>

        <div className="checkbox-row">
          <input
            id={consentId}
            name="training_consent"
            type="checkbox"
            checked={trainingConsent}
            onChange={(e) => setTrainingConsent(e.target.checked)}
          />
          <label htmlFor={consentId}>Allow verified crops for future OCR training</label>
        </div>

        {localError && (
          <p className="status-banner error" role="alert">
            {localError}
          </p>
        )}

        <button type="submit" className="primary" disabled={busy}>
          {busy ? "Importing PDF..." : "Import PDF"}
        </button>
      </form>
    </section>
  );
}
