# PDF fonts

Used by `make_pdf()` in `app.py` for SOP exports. All are from Google Fonts and licensed under the
SIL Open Font License 1.1 (https://openfontlicense.org), which allows bundling them with this app.

| File | Family | Used for |
|---|---|---|
| SourceSerif4_400Regular.ttf | Source Serif 4 (Adobe) | Title and section headings |
| Inter_400Regular.ttf / Inter_600SemiBold.ttf | Inter (Rasmus Andersson) | Body text, step titles, labels |
| JetBrainsMono_400Regular.ttf | JetBrains Mono (JetBrains) | Timestamps |

If this folder is missing, the app falls back to ReportLab's built-in Helvetica/Times/Courier.
