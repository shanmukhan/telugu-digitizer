export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function awaitScrollEndFallback(
  result: unknown,
  scroller: HTMLElement | Window,
  instant: boolean,
): Promise<void> {
  if (result && typeof (result as Promise<void>).then === "function") {
    return result as Promise<void>;
  }
  if (instant) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    let timerId: number | undefined;
    const finish = () => {
      if (timerId !== undefined) window.clearTimeout(timerId);
      scroller.removeEventListener("scrollend", finish);
      scroller.removeEventListener("scroll", onScroll);
      resolve();
    };
    const onScroll = () => {
      if (timerId !== undefined) window.clearTimeout(timerId);
      timerId = window.setTimeout(finish, 110);
    };
    scroller.addEventListener("scrollend", finish, { once: true });
    scroller.addEventListener("scroll", onScroll, { passive: true });
    timerId = window.setTimeout(finish, 110);
  });
}

export function scrollIntoViewAsync(
  element: HTMLElement,
  scroller: HTMLElement,
): Promise<void> {
  if (typeof element.scrollIntoView !== "function") {
    return Promise.resolve();
  }
  const instant = prefersReducedMotion();
  const result: unknown = element.scrollIntoView({
    behavior: instant ? "auto" : "smooth",
    block: "center",
    inline: "nearest",
  });
  return awaitScrollEndFallback(result, scroller, instant);
}

export function scrollContainerToAsync(
  scroller: HTMLElement,
  left: number,
  top: number,
): Promise<void> {
  if (typeof scroller.scrollTo !== "function") {
    return Promise.resolve();
  }
  const instant = prefersReducedMotion();
  const clampedLeft = Math.max(0, left);
  const clampedTop = Math.max(0, top);
  const result: unknown = scroller.scrollTo({
    left: clampedLeft,
    top: clampedTop,
    behavior: instant ? "auto" : "smooth",
  });
  return awaitScrollEndFallback(result, scroller, instant);
}
