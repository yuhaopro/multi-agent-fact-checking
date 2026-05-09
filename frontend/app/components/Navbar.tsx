"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const navLinks = [
  { href: "/", label: "Dashboard" },
  { href: "/eval", label: "Eval" },
  { href: "/logs", label: "Logs" },
];

export default function Navbar() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header
      style={{
        backgroundColor: "#fffefb",
        borderBottom: "1px solid #c5c0b1",
        position: "sticky",
        top: 0,
        zIndex: 50,
      }}
    >
      <div
        style={{
          maxWidth: "1200px",
          margin: "0 auto",
          padding: "0 24px",
          height: "64px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        {/* Logo */}
        <Link
          href="/"
          style={{
            textDecoration: "none",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: "28px",
              height: "28px",
              backgroundColor: "#ff4f00",
              borderRadius: "4px",
            }}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M8 1L14 5V11L8 15L2 11V5L8 1Z"
                stroke="#fffefb"
                strokeWidth="1.5"
                fill="none"
              />
              <path d="M5 8L7 10L11 6" stroke="#fffefb" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "16px",
              fontWeight: 600,
              color: "#201515",
            }}
          >
            FactCheck
          </span>
        </Link>

        {/* Desktop nav */}
        <nav
          style={{ display: "flex", alignItems: "center", gap: "0" }}
          className="hidden-mobile"
        >
          {navLinks.map(({ href, label }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "16px",
                  fontWeight: 500,
                  color: "#201515",
                  textDecoration: "none",
                  padding: "12px 16px",
                  boxShadow: active
                    ? "rgb(255, 79, 0) 0px -4px 0px 0px inset"
                    : "none",
                }}
                onMouseEnter={(e) => {
                  if (!active) {
                    (e.currentTarget as HTMLElement).style.boxShadow =
                      "rgb(197, 192, 177) 0px -4px 0px 0px inset";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!active) {
                    (e.currentTarget as HTMLElement).style.boxShadow = "none";
                  }
                }}
              >
                {label}
              </Link>
            );
          })}
        </nav>

        {/* CTA */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <Link
            href="/"
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "14px",
              fontWeight: 600,
              color: "#fffefb",
              backgroundColor: "#ff4f00",
              padding: "8px 16px",
              borderRadius: "4px",
              border: "1px solid #ff4f00",
              textDecoration: "none",
              whiteSpace: "nowrap",
            }}
          >
            Check a claim
          </Link>

          {/* Mobile hamburger */}
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            style={{
              display: "none",
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "4px",
              color: "#201515",
            }}
            className="mobile-menu-btn"
            aria-label="Toggle menu"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
              {menuOpen ? (
                <path
                  fillRule="evenodd"
                  d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                  clipRule="evenodd"
                />
              ) : (
                <path
                  fillRule="evenodd"
                  d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 15a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z"
                  clipRule="evenodd"
                />
              )}
            </svg>
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {menuOpen && (
        <div
          style={{
            borderTop: "1px solid #c5c0b1",
            backgroundColor: "#fffefb",
            padding: "8px 0",
          }}
          className="mobile-menu"
        >
          {navLinks.map(({ href, label }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setMenuOpen(false)}
                style={{
                  display: "block",
                  padding: "12px 24px",
                  fontFamily: "Inter, sans-serif",
                  fontSize: "16px",
                  fontWeight: 500,
                  color: active ? "#ff4f00" : "#201515",
                  textDecoration: "none",
                }}
              >
                {label}
              </Link>
            );
          })}
        </div>
      )}

      <style jsx>{`
        @media (max-width: 640px) {
          .hidden-mobile {
            display: none !important;
          }
          .mobile-menu-btn {
            display: block !important;
          }
        }
        @media (min-width: 641px) {
          .mobile-menu {
            display: none !important;
          }
        }
      `}</style>
    </header>
  );
}
