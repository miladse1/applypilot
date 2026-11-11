import type { MetadataRoute } from "next";

// Lets Chrome install ApplyPilot as an app with its own window and Dock icon.
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "ApplyPilot",
    short_name: "ApplyPilot",
    description: "Find early-career roles, tailor your resume, and prepare applications for your approval.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#4f46e5",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
