import { useToasts } from "../hooks/useToast";
import "../styles/components/toaster.css";

export function Toaster() {
  const toasts = useToasts();
  return (
    <div className="toaster">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          {t.msg}
        </div>
      ))}
    </div>
  );
}
