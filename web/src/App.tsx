import { Outlet } from "react-router-dom";
import { Toaster } from "./components/Toaster";
import { useLiveIndex } from "./hooks/useLiveIndex";
import "./styles/tokens.css";
import "./styles/layout.css";

export function App() {
  useLiveIndex();
  return (
    <>
      <Outlet />
      <Toaster />
    </>
  );
}
