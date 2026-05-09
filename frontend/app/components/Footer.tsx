export default function Footer() {
  return (
    <footer
      style={{
        backgroundColor: "#201515",
        color: "#fffefb",
        marginTop: "80px",
      }}
    >
      <div
        style={{
          maxWidth: "1200px",
          margin: "0 auto",
          padding: "48px 24px",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "40px",
        }}
      >
        {/* Brand */}
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              marginBottom: "16px",
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
                <path
                  d="M5 8L7 10L11 6"
                  stroke="#fffefb"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
            <span
              style={{
                fontFamily: "Inter, sans-serif",
                fontSize: "16px",
                fontWeight: 600,
                color: "#fffefb",
              }}
            >
              FactCheck
            </span>
          </div>
          <p
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "14px",
              fontWeight: 400,
              color: "#c5c0b1",
              lineHeight: 1.6,
              margin: 0,
              maxWidth: "240px",
            }}
          >
            Multi-agent AI pipeline for automated fact-checking and claim
            verification.
          </p>
        </div>

        {/* Links */}
        <div>
          <p
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "12px",
              fontWeight: 600,
              color: "#939084",
              textTransform: "uppercase",
              letterSpacing: "0.5px",
              marginBottom: "16px",
            }}
          >
            Product
          </p>
          {["Submit URL", "Eval Runner", "Admin Reset"].map((item) => (
            <p
              key={item}
              style={{
                fontFamily: "Inter, sans-serif",
                fontSize: "14px",
                color: "#c5c0b1",
                marginBottom: "8px",
              }}
            >
              {item}
            </p>
          ))}
        </div>

        {/* Pipeline */}
        <div>
          <p
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "12px",
              fontWeight: 600,
              color: "#939084",
              textTransform: "uppercase",
              letterSpacing: "0.5px",
              marginBottom: "16px",
            }}
          >
            Pipeline
          </p>
          {[
            "Post Creation",
            "Query Generation",
            "Evidence Retrieval",
            "Post Judge",
            "Media Verification",
          ].map((item) => (
            <p
              key={item}
              style={{
                fontFamily: "Inter, sans-serif",
                fontSize: "14px",
                color: "#c5c0b1",
                marginBottom: "8px",
              }}
            >
              {item}
            </p>
          ))}
        </div>
      </div>

      <div
        style={{
          borderTop: "1px solid #36342e",
          padding: "20px 24px",
          maxWidth: "1200px",
          margin: "0 auto",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "12px",
        }}
      >
        <p
          style={{
            fontFamily: "Inter, sans-serif",
            fontSize: "13px",
            color: "#939084",
            margin: 0,
          }}
        >
          &copy; {new Date().getFullYear()} FactCheck. Built with AI agents.
        </p>
        <p
          style={{
            fontFamily: "Inter, sans-serif",
            fontSize: "13px",
            color: "#939084",
            margin: 0,
          }}
        >
          Backend API on port{" "}
          <span style={{ color: "#c5c0b1", fontWeight: 500 }}>8081</span>
        </p>
      </div>
    </footer>
  );
}
