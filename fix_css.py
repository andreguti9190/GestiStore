import sys

path = r"C:\Users\Player 1\Desktop\GestiStore\Tienda\static\tienda\css\style.css"
c = open(path, "r", encoding="utf-8").read()

# Ensure copper vars exist
if "--amp-copper" not in c:
    c = c.replace("  --amp-header-height: 80px;\n  color-scheme: light;\n}", 
                  "  --amp-header-height: 80px;\n  --amp-copper: #ad7d43;\n  --amp-copper-soft: #e3c9a5;\n  color-scheme: light;\n}")

# Header/footer logo violet with gold accent
c = c.replace("  background: var(--amp-primary); color: var(--amp-white);",
              "  background: var(--amp-night); color: var(--amp-white); box-shadow: inset 0 -3px 0 var(--amp-copper);")
c = c.replace(".brand-logo {\nwidth: 44px; height: 44px; border-radius: 12px;\n  background: var(--amp-night); color: var(--amp-white);\n  display: flex; align-items: center; justify-content: center; flex-shrink: 0;\n}",
              ".brand-logo {\nwidth: 44px; height: 44px; border-radius: 12px;\n  background: var(--amp-night); color: var(--amp-white);\n  display: flex; align-items: center; justify-content: center; flex-shrink: 0;\n  box-shadow: inset 0 -3px 0 var(--amp-copper);\n}")

c = c.replace(".footer .brand-logo {\n  background: var(--amp-night);\n  box-shadow: none;\n}",
              ".footer .brand-logo {\n  background: rgba(255,255,255,.08);\n  box-shadow: inset 0 -3px 0 var(--amp-copper);\n}")

c = c.replace(".brand-sub {\n  color: var(--amp-muted);\n  font-weight: 500;\n}",
              ".brand-sub {\n  color: var(--amp-copper);\n  font-weight: 600;\n}")

# Footer colors
c = c.replace(".footer .brand-sub {\n  color: var(--amp-muted);\n}",
              ".footer .brand-sub {\n  color: var(--amp-copper-soft);\n}")
c = c.replace(".footer .brand-title {\n  color: var(--amp-night);\n}",
              ".footer .brand-title {\n  color: var(--amp-white);\n}")
c = c.replace(".footer {\n  border-top: 1px solid var(--amp-border);\n  position: relative;\n  background: var(--amp-white);\n}",
              ".footer {\n  border-top: none;\n  position: relative;\n  background: linear-gradient(160deg, var(--amp-night), #2b2858);\n}")
if ".footer::before" not in c:
    c = c.replace(".footer {\n  border-top: none;\n  position: relative;\n  background: linear-gradient(160deg, var(--amp-night), #2b2858);\n}",
                  ".footer {\n  border-top: none;\n  position: relative;\n  background: linear-gradient(160deg, var(--amp-night), #2b2858);\n}\n.footer::before {\n  content: '';\n  position: absolute;\n  left: 0;\n  right: 0;\n  top: 0;\n  height: 3px;\n  background: linear-gradient(90deg, var(--amp-primary), var(--amp-light) 60%, var(--amp-copper));\n}")

c = c.replace(".footer-contact a {\n  color: var(--amp-muted);\n}",
              ".footer-contact a {\n  color: var(--amp-soft);\n}")
c = c.replace(".footer-contact a:hover {\n  color: var(--amp-text);\n}",
              ".footer-contact a:hover {\n  color: var(--amp-white);\n}")
c = c.replace(".footer-right a {\n  color: var(--amp-muted);\n}",
              ".footer-right a {\n  color: var(--amp-white);\n}")
c = c.replace(".footer-right a:hover {\n  color: var(--amp-text);\n}",
              ".footer-right a:hover {\n  color: var(--amp-white);\n}")
c = c.replace(".footer-copy {\n  color: var(--amp-muted);\n}",
              ".footer-copy {\n  color: var(--amp-soft);\n}")

# Dark mode overrides
if "[data-theme=\"dark\"] .footer" in c:
    start = c.find("[data-theme=\"dark\"] .footer")
    end = c.find("\n[data-theme=", start + 1)
    if end == -1:
        end = c.find("\n.brand-logo", start + 1)
    new_block = """[data-theme="dark"] .footer {\n  background: linear-gradient(160deg, var(--amp-night), #2b2858);\n  border-top: none;\n}\n[data-theme="dark"] .footer::before {\n  content: '';\n  position: absolute;\n  left: 0;\n  right: 0;\n  top: 0;\n  height: 3px;\n  background: linear-gradient(90deg, var(--amp-primary), var(--amp-light) 60%, var(--amp-copper));\n  display: block;\n}\n[data-theme="dark"] .footer .brand-title { color: var(--amp-white); }\n[data-theme="dark"] .footer .brand-sub { color: var(--amp-copper-soft); }\n[data-theme="dark"] .footer .brand-logo { background: rgba(255,255,255,.08); box-shadow: inset 0 -3px 0 var(--amp-copper); }\n[data-theme="dark"] .footer-contact a { color: var(--amp-soft); }\n[data-theme="dark"] .footer-contact a:hover { color: var(--amp-white); }\n[data-theme="dark"] .footer-right a { color: var(--amp-white); }\n[data-theme="dark"] .footer-copy { color: var(--amp-soft); }\n[data-theme="dark"] .brand-logo { background: var(--amp-night); box-shadow: inset 0 -3px 0 var(--amp-copper); }\n[data-theme="dark"] .brand-sub { color: var(--amp-copper); }\n"""
    c = c[:start] + new_block + c[end:]

open(path, "w", encoding="utf-8").write(c)
print("done")
