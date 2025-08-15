import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";
import { useState, useEffect } from "react";

export default function DownloadMarkdown(props) {
  const [isDownloading, setIsDownloading] = useState(false);

  const downloadMarkdown = () => {
    setIsDownloading(true);

    // Use the content passed as a prop
    const markdownContent = props.content || '';

    const blob = new Blob([markdownContent], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = props.fileName || 'response.md';
    document.body.appendChild(a);
    a.click();

    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setIsDownloading(false);
    }, 100);
  };

  const [renderButton, setRenderButton] = useState(false);

  useEffect(() => {
    setRenderButton(true);
  }, []);

  return renderButton ? (
    <Button
      onClick={downloadMarkdown}
      disabled={isDownloading}
      className="flex items-center gap-2"
    >
      <Download size={16} />
      {isDownloading ? "Downloading..." : props.buttonText || "Download as Markdown"}
    </Button>
  ) : null;
}

