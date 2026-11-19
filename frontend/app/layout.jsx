import "./globals.css";
import Shell from "../components/Shell";
export const metadata = {
  title: "Corvo Procure · Procurement Workspace",
  description:
    "Policy-driven purchase request intake, sourcing and purchase order decisions",
};
export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
