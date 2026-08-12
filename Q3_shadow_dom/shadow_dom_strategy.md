# Q3 — Sealed Closed-Boundary Shadow DOM Pathfinding & Accessibility Tree Refactoring

## Part A: Resilient Shadow DOM Traversal Strategy

### Problem

Standard DOM queries (`querySelector`, `getElementById`) **cannot pierce Shadow DOM boundaries** by default.  
When shadow hosts use obfuscated class strings that regenerate on every page reload (e.g., `obfuscated_v4_x89a`), class-based selectors are completely unreliable.

### Strategy: Recursive Shadow Root Piercing

The core insight is to **never rely on class names or IDs**. Instead, target elements using stable semantic attributes: `data-*`, `role`, `aria-*`, and structural position within the shadow tree.

```js
/**
 * Recursively searches all shadow roots for an element matching `selector`.
 * `selector` MUST use only attribute predicates — no class or ID selectors.
 *
 * Example usage:
 *   const btn = deepQuerySelector(document, '[data-qa-state="unlocked-token"]');
 *
 * @param {Document|Element|ShadowRoot} root
 * @param {string} selector  — Attribute-based CSS selector only
 * @returns {Element|null}
 */
function deepQuerySelector(root, selector) {
  // Try matching in the current scope first
  const directMatch = root.querySelector(selector);
  if (directMatch) return directMatch;

  // Enumerate all elements and recurse into any shadow roots
  const allElements = root.querySelectorAll('*');
  for (const el of allElements) {
    if (el.shadowRoot) {
      const found = deepQuerySelector(el.shadowRoot, selector);
      if (found) return found;
    }
  }
  return null;
}
```

### Handling Closed Shadow Roots

`closed` shadow roots (`attachShadow({ mode: 'closed' })`) do not expose `.shadowRoot`. Two approaches:

**Approach 1 — Native Accessibility API (preferred for automation):**  
Use `ElementInternals` or browser-native accessibility tree traversal. In Playwright/CDP:

```python
# Playwright CDP session — pierce ALL shadow boundaries natively
client = await page.context.new_cdp_session(page)
result = await client.send("DOM.getDocument", {"pierce": True, "depth": -1})
# Then query via DOM.querySelector with pierce=True
node = await client.send("DOM.querySelector", {
    "nodeId": result["root"]["nodeId"],
    "selector": "[data-qa-state='unlocked-token']"
})
```

**Approach 2 — Constructor patching (dev/test environments only):**

```js
// Intercept attachShadow before page scripts run (inject via CDP Runtime.addScriptOnNewDocument)
const _attachShadow = Element.prototype.attachShadow;
Element.prototype.attachShadow = function(init) {
  const shadow = _attachShadow.call(this, { ...init, mode: 'open' });
  this.__shadowRoot = shadow;  // preserve reference
  return shadow;
};

// Now access closed roots via:
function getAnyShadowRoot(el) {
  return el.shadowRoot || el.__shadowRoot || null;
}
```

**Approach 3 — MutationObserver for dynamically injected hosts:**

```js
const observer = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    for (const node of mutation.addedNodes) {
      if (node.shadowRoot || node.__shadowRoot) {
        const target = deepQuerySelector(
          node.shadowRoot || node.__shadowRoot,
          '[data-qa-state="unlocked-token"]'
        );
        if (target) {
          observer.disconnect();
          target.click();
        }
      }
    }
  }
});
observer.observe(document.body, { childList: true, subtree: true });
```

### Applied to the Example DOM

Given:
```html
<enterprise-portal id="root-gateway">
  #shadow-root (open)
    <payment-terminal class="obfuscated_v4_x89a">   ← class is obfuscated, ignore it
      #shadow-root (closed)
        <security-sandbox id="iframe-sandbox-wrapper">
          #shadow-root (open)
            <button class="trigger-finalize" data-qa-state="unlocked-token">
              Authorize Ledger Funds
            </button>
```

**Stable selectors to use:**
- `[data-qa-state="unlocked-token"]`   — most reliable, survives class regeneration
- `security-sandbox` (tag name)        — custom element name is stable
- `role="button"` + `aria-label`       — if aria attributes are set

**Playwright implementation:**
```python
# Pierces all shadow boundaries using CDP
btn = page.locator("pierce=[data-qa-state='unlocked-token']")
await btn.click()
```

---

## Part B: Expert LLM Chain-of-Thought System Prompt

> See `cot_prompt.md`

---

## Summary

| Technique | When to Use |
|-----------|-------------|
| `deepQuerySelector` recursive | Open shadow roots, standard test envs |
| CDP `DOM.querySelector` with `pierce` | Any shadow mode, Playwright/CDP |
| `attachShadow` constructor patch | Closed shadow roots in controlled envs |
| `MutationObserver` | Dynamically injected shadow hosts |
| `data-qa-*` / `aria-*` attributes | Always — never use class/ID selectors |
