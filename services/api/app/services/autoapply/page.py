"""Read the questions on a page and fill them in, using Playwright's sync API.

Hidden inputs and honeypots (fields marked "for robots only" or "leave blank") are never
touched. Nothing here clicks a submit button; the driver decides that.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.services.autoapply.fields import Field, choose_option

log = logging.getLogger(__name__)

READ_FIELDS = r"""
() => {
  const HONEYPOT = /robot|honeypot|leave (this )?(field )?(blank|empty)|do not (enter|fill|type)|bot field/i;
  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    if (el.closest('[aria-hidden="true"]')) return false;
    return true;
  };
  const text = (el) => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const labelOf = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && text(l)) return text(l);
    }
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map((i) => text(document.getElementById(i))).join(' ').trim();
      if (t) return t;
    }
    const wd = el.closest('[data-automation-id^="formField-"]');
    if (wd) { const l = wd.querySelector('label, legend'); if (l && text(l)) return text(l); }
    const fs = el.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg && text(lg)) return text(lg); }
    const wrap = el.closest('label');
    if (wrap && text(wrap)) return text(wrap);
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    // Nearest label-like text above the control within its field container.
    let node = el.parentElement;
    for (let depth = 0; node && depth < 4; depth++, node = node.parentElement) {
      const l = node.querySelector(':scope > label, :scope > legend, :scope > div > label, :scope > [class*="label" i], :scope > [class*="question" i]');
      if (l && !l.contains(el) && text(l)) return text(l);
    }
    return el.getAttribute('placeholder') || '';
  };
  const requiredOf = (el, label) => !!(el.required || el.getAttribute('aria-required') === 'true' || /[*✱]\s*$/.test(label) || (el.closest('[data-automation-id^="formField-"]') || {}).innerText?.includes('*'));
  const fields = [];
  let n = 0;
  const tag = (el) => { const id = 'f' + (n++); el.setAttribute('data-ap', id); return id; };
  document.querySelectorAll('[data-ap]').forEach((el) => { el.removeAttribute('data-ap'); el.removeAttribute('data-ap-opt'); });
  const groups = {};
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const type = (el.type || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) continue;
    if (el.disabled || el.readOnly && type !== 'file') continue;
    const label = labelOf(el);
    const meta = `${label} ${el.name || ''} ${el.placeholder || ''} ${el.getAttribute('data-automation-id') || ''}`;
    if (HONEYPOT.test(meta) || el.getAttribute('data-automation-id') === 'beecatcher') continue;
    if (type === 'file') {
      // Upload buttons are often all labelled "Attach"; the surrounding heading says which document it is.
      let context = '';
      for (let node = el.parentElement, depth = 0; node && depth < 4 && !context; depth++, node = node.parentElement) {
        const t = text(node);
        if (t && t.length <= 240 && t.replace(/attach|upload|enter manually|choose file|drop.*here/gi, '').trim().length > 2) context = t;
      }
      fields.push({id: tag(el), kind: 'file', label, required: requiredOf(el, label) || /[*✱]/.test(context), options: [], value: el.files && el.files.length ? el.files[0].name : '', name: el.name || '', accept: el.accept || '', domId: el.id || '', context});
      continue;
    }
    if (type === 'radio' || type === 'checkbox') {
      const optLabel = (() => { const l = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`); return text(l || el.closest('label')) || el.value || el.getAttribute('aria-label') || ''; })();
      const target = visible(el) ? el : (el.closest('label') || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)));
      if (!visible(target)) continue;
      const key = (el.name || el.id) + '|' + type;
      const container = el.closest('fieldset, [role="radiogroup"], [role="group"], [data-automation-id^="formField-"]') || el.parentElement?.parentElement;
      const groupLabel = (() => {
        if (container) {
          const lg = container.querySelector('legend, label:not(:has(input))');
          if (lg && text(lg) && text(lg) !== optLabel) return text(lg);
          const by = container.getAttribute('aria-labelledby');
          if (by) return by.split(/\s+/).map((i) => text(document.getElementById(i))).join(' ');
        }
        let node = container;
        for (let depth = 0; node && depth < 4; depth++, node = node.parentElement) {
          const l = node.querySelector(':scope > label, :scope > legend, :scope > div > label, :scope > [class*="label" i], :scope > [class*="question" i]');
          if (l && text(l) && !/^(yes|no)$/i.test(text(l)) && text(l) !== optLabel) return text(l);
        }
        return '';
      })();
      if (!groups[key]) {
        groups[key] = {id: 'f' + (n++), kind: type, label: groupLabel || optLabel, optionLabel: optLabel, required: false, options: [], value: '', name: el.name || ''};
        fields.push(groups[key]);
      }
      const g = groups[key];
      el.setAttribute('data-ap', g.id);
      el.setAttribute('data-ap-opt', String(g.options.length));
      g.options.push(optLabel);
      // A lone checkbox ("I have a preferred name") is required only when the page marks the box itself.
      g.required = g.required || el.required || el.getAttribute('aria-required') === 'true' || (type === 'radio' && /[*✱]/.test(g.label));
      if (el.checked) g.value = g.value ? g.value + '; ' + optLabel : optLabel;
      continue;
    }
    if (!visible(el)) continue;
    const role = el.getAttribute('role');
    const isCombo = role === 'combobox' || el.getAttribute('aria-autocomplete') === 'list' || /select__input|react-select/.test(el.className || '');
    const kind = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : isCombo ? 'combobox' : (['email', 'tel', 'url', 'number', 'date'].includes(type) ? type : 'text');
    let value = el.value || '';
    if (isCombo) {
      const box = el.closest('[class*="select__control" i], [class*="container" i]');
      const single = box && box.querySelector('[class*="single-value" i], [class*="singleValue" i]');
      if (single) value = text(single);
    }
    const options = el.tagName === 'SELECT' ? [...el.options].map((o) => o.text.trim()).filter(Boolean) : [];
    if (el.tagName === 'SELECT' && el.selectedIndex > 0) value = el.options[el.selectedIndex].text.trim(); else if (el.tagName === 'SELECT') value = '';
    fields.push({id: tag(el), kind, label, required: requiredOf(el, label), options, value, name: el.name || '', placeholder: el.placeholder || '', invalid: el.getAttribute('aria-invalid') === 'true', domId: el.id || '', maxlength: el.maxLength > 0 ? el.maxLength : null});
  }
  // Workday dropdowns are buttons that open a listbox.
  for (const el of document.querySelectorAll('button[aria-haspopup="listbox"]')) {
    if (!visible(el) || el.hasAttribute('data-ap')) continue;
    const label = labelOf(el);
    if (!label) continue;
    const value = text(el).replace(/^select one$/i, '');
    fields.push({id: tag(el), kind: 'listbox', label, required: requiredOf(el, label), options: [], value, name: '', invalid: el.getAttribute('aria-invalid') === 'true'});
  }
  // Yes/No answered with buttons (Ashby).
  const seen = new Set();
  for (const button of document.querySelectorAll('button')) {
    if (!/^(yes|no)$/i.test(text(button)) || !visible(button)) continue;
    const box = button.parentElement;
    if (!box || seen.has(box)) continue;
    const buttons = [...box.querySelectorAll(':scope > button')];
    if (buttons.length < 2 || !buttons.every((b) => /^(yes|no)$/i.test(text(b)))) continue;
    seen.add(box);
    let label = '';
    for (let node = box.parentElement, depth = 0; node && depth < 4 && !label; depth++, node = node.parentElement) {
      const l = node.querySelector(':scope > label, :scope > legend, :scope > div > label');
      if (l && text(l)) label = text(l);
    }
    const id = 'f' + (n++);
    buttons.forEach((b, i) => { b.setAttribute('data-ap', id); b.setAttribute('data-ap-opt', String(i)); });
    const chosen = buttons.find((b) => b.getAttribute('aria-pressed') === 'true' || /active|selected/i.test(b.className));
    fields.push({id, kind: 'buttons', label, required: /[*✱]/.test(label), options: buttons.map(text), value: chosen ? text(chosen) : '', name: ''});
  }
  return fields.map((f) => ({...f, label: (f.label || '').slice(0, 500)}));
}
"""

ERRORS = r"""
() => {
  const out = new Set();
  for (const el of document.querySelectorAll('[role="alert"], [data-automation-id="errorMessage"], [data-automation-id="inputAlert"], .error, .error-message, [class*="error" i][aria-live], [id*="error" i]')) {
    const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
    const r = el.getBoundingClientRect();
    if (t && t.length < 300 && r.width > 0 && r.height > 0) out.add(t);
  }
  return [...out].slice(0, 12);
}
"""


def read_fields(page) -> list[Field]:
    raw = page.evaluate(READ_FIELDS)
    fields = []
    for item in raw:
        label = item.get("label") or ""
        option_label = item.get("optionLabel") or ""
        if item["kind"] == "checkbox" and len(item.get("options") or []) == 1 and option_label and option_label not in label:
            label = f"{label} {option_label}".strip()
        fields.append(
            Field(
                id=item["id"],
                kind=item["kind"],
                label=label,
                required=bool(item.get("required")),
                options=[option for option in item.get("options") or [] if option],
                value=item.get("value") or "",
                name=item.get("name") or "",
                placeholder=item.get("placeholder") or "",
                accept=item.get("accept") or "",
                invalid=bool(item.get("invalid")),
                dom_id=item.get("domId") or "",
                context=item.get("context") or "",
                maxlength=item.get("maxlength"),
            )
        )
    return fields


def page_errors(page) -> list[str]:
    try:
        return page.evaluate(ERRORS)
    except Exception:  # noqa: BLE001
        return []


def _visible_options(page) -> list:
    options = page.locator('[role="option"]:visible, [data-automation-id="promptOption"]:visible, .select__option:visible')
    return [options.nth(i) for i in range(min(options.count(), 80))]


def read_dropdown_options(page, field: Field) -> list[str]:
    """Open a combobox or Workday listbox to see its options, then close it again."""
    target = page.locator(f'[data-ap="{field.id}"]').first
    try:
        target.click(timeout=4000)
        page.wait_for_timeout(500)
        options = [item.inner_text().strip() for item in _visible_options(page)]
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        return [option for option in options if option]
    except Exception:  # noqa: BLE001
        return []


def fill_field(page, field: Field, value) -> bool:
    """Put one value into one field. Returns True when the page shows the value afterwards."""
    locator = page.locator(f'[data-ap="{field.id}"]')
    try:
        if field.kind == "file":
            path = Path(value)
            locator.first.set_input_files(str(path), timeout=10000)
            page.wait_for_timeout(1500)
            # Confirm the page took this exact file: the input holds it, or the site shows its name.
            attached = locator.first.evaluate("(el) => el.files && el.files.length ? el.files[0].name : ''")
            return attached == path.name or path.name in (page.locator("body").inner_text(timeout=3000) or "")
        if field.kind in {"text", "textarea", "email", "tel", "url", "number", "date"}:
            target = locator.first
            target.fill(str(value), timeout=8000)
            target.dispatch_event("change")
            # Location fields and type-to-search boxes suggest options; take the one that matches.
            typeahead = target.evaluate("(el) => !!(el.getAttribute('aria-autocomplete') || el.getAttribute('aria-controls') || el.getAttribute('aria-haspopup') || el.closest('[data-uxi-widget-type], [data-automation-id*=\"prompt\" i], [data-automation-id*=\"multiselect\" i]'))")
            if field.kind == "text" and (typeahead or re.search(r"location|city|address", field.label, re.I)):
                page.wait_for_timeout(1200)
                suggestion = _pick_option(page, str(value))
                if suggestion is not None:
                    suggestion.click(timeout=3000)
            target.evaluate("(el) => el.blur()")
            return True
        if field.kind == "select":
            locator.first.select_option(label=str(value), timeout=8000)
            return True
        if field.kind == "checkbox_group":
            for choice in value if isinstance(value, list) else [value]:
                option = page.locator(f'[data-ap="{field.id}"][data-ap-opt="{field.options.index(choice)}"]').first
                try:
                    option.check(timeout=4000)
                except Exception:  # noqa: BLE001
                    option.evaluate("(el) => (el.closest('label') || el).click()")
            return True
        if field.kind == "radio":
            index = field.options.index(value)
            option = page.locator(f'[data-ap="{field.id}"][data-ap-opt="{index}"]').first
            try:
                option.check(timeout=4000)
            except Exception:  # noqa: BLE001 - styled inputs: click their label instead
                option.evaluate("(el) => (el.closest('label') || document.querySelector(`label[for=\"${el.id}\"]`) || el).click()")
            return True
        if field.kind == "checkbox":
            option = locator.first
            if bool(value):
                try:
                    option.check(timeout=4000)
                except Exception:  # noqa: BLE001
                    option.evaluate("(el) => (el.closest('label') || document.querySelector(`label[for=\"${el.id}\"]`) || el).click()")
            return True
        if field.kind == "buttons":
            index = field.options.index(value)
            page.locator(f'[data-ap="{field.id}"][data-ap-opt="{index}"]').first.click(timeout=4000)
            return True
        if field.kind in {"combobox", "listbox"}:
            target = locator.first
            target.click(timeout=4000)
            page.wait_for_timeout(400)
            if field.kind == "combobox":
                target.fill(str(value), timeout=4000)
                page.wait_for_timeout(800)
            choice = _pick_option(page, str(value))
            if choice is None and field.kind == "listbox":
                search = page.locator('[data-automation-id="searchBox"]:visible input, input[data-automation-id="searchBox"]:visible')
                if search.count():
                    search.first.fill(str(value))
                    search.first.press("Enter")
                    page.wait_for_timeout(1000)
                    choice = _pick_option(page, str(value))
            if choice is None:
                page.keyboard.press("Escape")
                return False
            choice.click(timeout=4000)
            page.wait_for_timeout(300)
            return True
    except Exception as exc:  # noqa: BLE001 - a field we cannot fill is reported, not fatal
        log.info("Could not fill %r: %s", field.label[:60], exc)
        return False
    return False


def _pick_option(page, value: str):
    options = _visible_options(page)
    if not options:
        return None
    texts = [item.inner_text().strip() for item in options]
    chosen = choose_option(value, texts)
    if chosen is None:
        return None
    return options[texts.index(chosen)]
