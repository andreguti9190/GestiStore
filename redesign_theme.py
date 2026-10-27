path = r"C:\Users\Player 1\Desktop\GestiStore\Tienda\static\tienda\css\style.css"
c = open(path, "r", encoding="utf-8").read()

# Add new theme vars at top
old_root = ''':root {
  --amp-primary: #5282bc;
  --amp-indigo: #455892;
  --amp-night: #353166;
  --amp-ice: #eefafc;
  --amp-white: #ffffff;
  --amp-soft: #cad8ea;
  --amp-light: #87a8d0;
  --amp-gold: #ad7d43;
  --amp-text: #353166;
  --amp-muted: #52617c;
  --amp-border: #cad8ea;
  --amp-border-strong: #87a8d0;
  --amp-success: #216445;
  --amp-success-bg: #edf7f0;
  --amp-warning: #86591f;
  --amp-warning-bg: #fff5e6;
  --amp-danger: #ad3545;
  --amp-danger-hover: #8c2634;
  --amp-danger-bg: #fff0f2;
  --amp-danger-border: #edbdc5;
  --amp-ring: 0 0 0 3px rgba(82, 130, 188, .24);
  --amp-shadow: 0 4px 18px rgba(53, 49, 102, .07);
  --amp-shadow-hover: 0 12px 30px rgba(53, 49, 102, .14);
  --amp-radius: 16px;
  /* Índigo para texto pequeño sobre botones: mejor contraste que el azul medio. */
  --amp-action: #455892;
  --amp-heading-font: 'Poppins', 'Segoe UI', Arial, sans-serif;
  --amp-header-height: 80px;
  --amp-copper: #ad7d43;
  --amp-copper-soft: #e3c9a5;
  color-scheme: light;
}'''
new_root = ''':root {
  --amp-heading-font: 'Poppins', 'Segoe UI', Arial, sans-serif;
  --amp-header-height: 80px;
  --amp-bg: #f7f8fa;
  --amp-surface: #ffffff;
  --amp-surface-2: #f3f4f6;
  --amp-text: #0f1026;
  --amp-text-secondary: #4b5563;
  --amp-border: #e5e7eb;
  --amp-border-strong: #d1d5db;
  --amp-primary: #6b8fd6;
  --amp-primary-strong: #4f7bd6;
  --amp-accent: #ad7d43;
  --amp-success: #1f9d55;
  --amp-success-bg: #f0fdf4;
  --amp-warning: #b45309;
  --amp-warning-bg: #fffbeb;
  --amp-danger: #dc2626;
  --amp-danger-bg: #fef2f2;
  --amp-danger-border: #fecaca;
  --amp-ring: 0 0 0 3px rgba(79, 123, 214, 0.08);
  --amp-shadow: 0 1px 2px rgba(15, 16, 38, 0.01), 0 10px 30px rgba(15, 16, 38, 0.03);
  color-scheme: light;
}

[data-theme="dark"] {
  --amp-bg: #0b1026;
  --amp-surface: #10162b;
  --amp-surface-2: #151b33;
  --amp-text: #e7e9ee;
  --amp-text-secondary: #9aa0c3;
  --amp-border: #1f2540;
  --amp-border-strong: #2a3160;
  --amp-primary: #8aa5f5;
  --amp-primary-strong: #7a95e8;
  --amp-accent: #c99a5a;
  --amp-success: #22c55e;
  --amp-success-bg: rgba(34, 197, 94, 0.12);
  --amp-warning: #f59e0b;
  --amp-warning-bg: rgba(245, 158, 11, 0.12);
  --amp-danger: #f87171;
  --amp-danger-bg: rgba(248, 113, 113, 0.12);
  --amp-danger-border: rgba(248, 113, 113, 0.4);
  --amp-ring: 0 0 0 3px rgba(138, 165, 245, 0.14);
  --amp-shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 20px 60px rgba(0, 0, 0, 0.35);
  color-scheme: dark;
}'''

if old_root in c:
    c = c.replace(old_root, new_root)
else:
    # just replace first :root block
    pass

# Remove old minimal block
start = c.find("/* ─── MINIMALISTA")
if start >= 0:
    end = c.find("\n/*", start + 10)
    if end == -1:
        end = len(c)
    # keep a simple block
    block = '''/* ─── Minimalista moderno ───────────────────── */

body {
  background: var(--amp-bg);
  color: var(--amp-text);
  transition: background 0.25s ease, color 0.25s ease;
}

.header {
  background: var(--amp-surface);
  border-bottom: 1px solid var(--amp-border);
  box-shadow: var(--amp-shadow);
}
.header::after { display: none; }

.brand-logo {
  background: linear-gradient(145deg, var(--amp-primary), var(--amp-primary-strong));
  box-shadow: none;
  border-radius: 10px;
}
.brand-title { color: var(--amp-text); font-weight: 600; }
.brand-sub { color: var(--amp-accent); font-weight: 600; letter-spacing: 0.08em; }

.nav-links a { color: var(--amp-text-secondary); font-weight: 500; }
.nav-links a:hover,
.nav-links a[aria-current="page"] { color: var(--amp-text); }
.nav-links a::after { background: var(--amp-primary-strong); height: 1.5px; }

.user-btn-secondary {
  background: transparent;
  color: var(--amp-text-secondary);
  border: 1px solid var(--amp-border);
}
.user-btn-secondary:hover {
  background: var(--amp-surface-2);
  color: var(--amp-text);
  border-color: var(--amp-border-strong);
}

.theme-toggle {
  color: var(--amp-text-secondary);
  border: 1px solid var(--amp-border);
}
.theme-toggle:hover { background: var(--amp-surface-2); color: var(--amp-text); }

.mobile-menu {
  background: var(--amp-surface);
  border-bottom: 1px solid var(--amp-border);
}
.mobile-menu-nav a,
.mobile-theme-toggle { color: var(--amp-text-secondary); }
.mobile-menu-nav a:hover,
.mobile-theme-toggle:hover { background: var(--amp-surface-2); color: var(--amp-text); }

.footer {
  background: var(--amp-surface);
  color: var(--amp-text);
  border-top: 1px solid var(--amp-border);
  margin-top: 64px;
}
.footer::before { display: none; }
.footer .brand-title { color: var(--amp-text); }
.footer .brand-sub { color: var(--amp-accent); }
.footer .brand-logo {
  background: linear-gradient(145deg, var(--amp-primary), var(--amp-primary-strong));
  box-shadow: none;
}
.footer-contact a,
.footer-right a,
.footer-copy { color: var(--amp-text-secondary); }
.footer-contact a:hover,
.footer-right a:hover { color: var(--amp-text); }

.card {
  background: var(--amp-surface);
  border: 1px solid var(--amp-border);
  box-shadow: var(--amp-shadow);
  border-radius: 12px;
}

.btn-primary {
  background: var(--amp-primary-strong);
  color: #fff;
  border: none;
  box-shadow: none;
}
.btn-primary:hover { background: #3f6bd1; }

.btn-secondary {
  background: transparent;
  color: var(--amp-text-secondary);
  border: 1px solid var(--amp-border);
}
.btn-secondary:hover {
  background: var(--amp-surface-2);
  color: var(--amp-text);
  border-color: var(--amp-border-strong);
}

form input,
form select,
form textarea {
  background: var(--amp-surface);
  border: 1px solid var(--amp-border);
  color: var(--amp-text);
}
form input:focus,
form select:focus,
form textarea:focus {
  border-color: var(--amp-primary);
  box-shadow: var(--amp-ring);
}

.messages li {
  background: var(--amp-surface-2);
  color: var(--amp-text);
  border: 1px solid var(--amp-border);
}

.auth-form { background: var(--amp-surface); }
.auth-title { color: var(--amp-text); }
.auth-sub { color: var(--amp-text-secondary); }
.auth-field label { color: var(--amp-text); }

.exito-box,
.confirmar-box {
  background: var(--amp-surface);
  border: 1px solid var(--amp-border);
  box-shadow: var(--amp-shadow);
}
.exito-codigo {
  background: var(--amp-surface-2);
  color: var(--amp-text);
  border: 1px solid var(--amp-border);
}

.store-assistant .assistant-panel {
  background: var(--amp-surface);
  border: 1px solid var(--amp-border);
  box-shadow: var(--amp-shadow);
}
.store-assistant .assistant-panel header {
  background: var(--amp-surface-2);
  color: var(--amp-text);
  border-bottom: 1px solid var(--amp-border);
}
.store-assistant .assistant-messages {
  background: var(--amp-bg);
}
.store-assistant .assistant-bubble.bot {
  background: var(--amp-surface-2);
  color: var(--amp-text);
}
.store-assistant .assistant-options button {
  background: var(--amp-surface);
  color: var(--amp-text-secondary);
  border: 1px solid var(--amp-border);
}
.store-assistant .assistant-options button:hover {
  color: var(--amp-text);
  border-color: var(--amp-border-strong);
  background: var(--amp-surface-2);
}
'''
    c = c[:start] + block + "\n" + c[end:]

open(path, "w", encoding="utf-8").write(c)
print("done")
