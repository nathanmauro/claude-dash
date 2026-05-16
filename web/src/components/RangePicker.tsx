import { useSearchParams } from "react-router-dom";
import { isoDate, shiftDate } from "../utils/format";

export function RangePicker() {
  const [params, setParams] = useSearchParams();
  const today = isoDate(new Date());

  const date = params.get("date");
  const fromParam = params.get("from");
  const toParam = params.get("to");

  const start = date ?? fromParam ?? toParam ?? today;
  const end = date ?? toParam ?? fromParam ?? today;

  const isToday = start === today && end === today && !fromParam && !toParam;
  const sevenStart = shiftDate(today, -6);
  const thirtyStart = shiftDate(today, -29);
  const is7d = !date && fromParam === sevenStart && toParam === today;
  const is30d = !date && fromParam === thirtyStart && toParam === today;

  function setRange(from: string, to: string) {
    const p = new URLSearchParams();
    p.set("from", from);
    p.set("to", to);
    setParams(p);
  }
  function clearRange() {
    setParams(new URLSearchParams());
  }
  function shift(days: number) {
    const p = new URLSearchParams();
    if (date) {
      p.set("date", shiftDate(date, days));
    } else {
      p.set("from", shiftDate(start, days));
      p.set("to", shiftDate(end, days));
    }
    setParams(p);
  }
  function onFromChange(e: React.ChangeEvent<HTMLInputElement>) {
    const p = new URLSearchParams();
    p.set("from", e.target.value);
    p.set("to", end);
    setParams(p);
  }
  function onToChange(e: React.ChangeEvent<HTMLInputElement>) {
    const p = new URLSearchParams();
    p.set("from", start);
    p.set("to", e.target.value);
    setParams(p);
  }

  return (
    <nav className="range-picker" aria-label="date range">
      <button className="step" type="button" onClick={() => shift(-1)} title="shift 1 day earlier (←)">
        ←
      </button>
      <div className="range-form">
        <input type="date" value={start} max={end} onChange={onFromChange} aria-label="from" />
        <span className="sep">→</span>
        <input type="date" value={end} max={today} onChange={onToChange} aria-label="to" />
      </div>
      <button className="step" type="button" onClick={() => shift(1)} title="shift 1 day later (→)">
        →
      </button>
      <div className="quick">
        <button type="button" className={isToday ? "active" : ""} onClick={clearRange}>
          Today
        </button>
        <button type="button" className={is7d ? "active" : ""} onClick={() => setRange(sevenStart, today)}>
          7d
        </button>
        <button type="button" className={is30d ? "active" : ""} onClick={() => setRange(thirtyStart, today)}>
          30d
        </button>
      </div>
    </nav>
  );
}
