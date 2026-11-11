"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * A link to drag to the bookmarks bar. React blocks `javascript:` links it renders, so the
 * bookmark code is set on the element directly after it mounts.
 */
export function Bookmarklet({ code, children, className }: { code: string; children: ReactNode; className?: string }) {
  const ref = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    if (ref.current && code) ref.current.setAttribute("href", code);
  }, [code]);
  return (
    <a ref={ref} onClick={(event) => event.preventDefault()} draggable className={className} title="Drag this to your bookmarks bar">
      {children}
    </a>
  );
}

/**
 * The Experience York bookmark. In the user's own browser it copies the page on screen (a posting
 * or a posting list, without scripts or images) and opens ApplyPilot on this computer with it.
 * It sends no request to York and nothing leaves the computer.
 */
export function yorkBookmarklet(origin: string) {
  return (
    "javascript:(()=>{const c=document.documentElement.cloneNode(true);" +
    "c.querySelectorAll('script:not([type=\"application/ld+json\"]),style,svg,noscript,iframe,img,video,link,meta,canvas').forEach(e=>e.remove());" +
    "const h=c.outerHTML.replace(/\\s{2,}/g,' ');" +
    "if(h.length>900000){alert('This page is too large for the bookmark. Save it with File > Save Page As and import the file in ApplyPilot.');return;}" +
    `window.open('${origin}/york/import#'+encodeURIComponent(JSON.stringify({url:location.href,html:h})),'_blank');})();`
  );
}
