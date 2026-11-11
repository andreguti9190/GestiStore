---
name: AmpereStore
description: Cobalt parts index for a clear, efficient technology storefront.
colors:
  primary: "#315f8a"
  primary-deep: "#244968"
  neutral-bg: "#f5f7f8"
  surface: "#ffffff"
  text: "#1b2430"
  text-muted: "#596573"
  border: "#d8dee4"
  category-hover: "#e9f0f6"
  hero-dark: "#172c3e"
  hero-secondary: "#e5eef5"
  icon-line: "#c7d7e5"
  success: "#216a48"
  warning: "#805b26"
  danger: "#a63a3a"
  focus: "#d1a56d"
typography:
  display:
    fontFamily: "Inter, Segoe UI, Arial, sans-serif"
    fontSize: "clamp(2rem, 4.5vw, 3.5rem)"
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-0.035em"
  body:
    fontFamily: "Inter, Noto Sans, Segoe UI, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sm: "6px"
  md: "9px"
  lg: "12px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "0 18px"
    height: "44px"
  product-index:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: "16px"
---

# Design System: AmpereStore

## Overview

The approved visual direction is **Índice de repuestos**: a clear parts catalogue that takes shoppers from category to product while keeping price and availability easy to compare. The owner asked to preserve the AmpereStore logo, blue identity, and current functions. Use real product photography and existing product data. The site is a storefront, not an internal inventory console.

## Colors

Use cobalt blue for primary actions and wayfinding. Deep blue anchors the homepage hero; pale blue-white supports secondary text on that dark surface. White and cool gray surfaces keep long product names and prices readable. Green, amber, and red are reserved for stock states and must also include text labels.

## Typography

Continue the existing Inter family. Use a compact, confident headline, plain body text, and tabular figures for prices and quantities. Keep product labels legible; do not use monospace as a technical costume.

## Layout

The homepage starts with a direct search and a single recent-product feature, followed by a compact category index and recent products. The index is a list of navigable categories, not a wall of equal promotional cards. On narrow screens the hero stacks, the category index becomes two columns, and products remain two columns until the smallest breakpoint.

## Elevation & Depth

Prefer boundaries and surface contrast over shadows. Reserve one low, soft elevation for the global navigation; homepage product and category content use borders.

## Shapes

Use restrained 6–12px radii on controls and product surfaces. Search and action buttons have clear keyboard focus. Avoid pills for large content and avoid decorative glass effects.

## Components

- **Search:** white, labeled input and a visible submit button inside the blue hero; search submits to the existing catalog query.
- **Recent-product feature:** real product image, category, stock wording, and price in ARS. Empty state remains useful when there are no active products.
- **Category index:** existing categories and destinations, presented as linked rows with consistent line icons.
- **Product listing:** existing product data and detail routes, with category, name, ARS price, and explicit stock state.
- **Admin action:** retain the current add-product route for authenticated administrators.

## Do's and Don'ts

- Keep the existing logo and cobalt identity.
- Keep all existing shopping and seller actions connected to their current routes.
- Show only verified store claims; no speed metrics, delivery promises, or compatibility guarantees were supplied.
- Keep the catalog searchable and scannable; do not repeat the featured product in the recent-product list.
- Do not replace product photographs with invented art or turn the storefront into a dashboard.
