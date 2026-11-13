Summarise a query result table for a clinical researcher in at most 3 short sentences.
A strict program checks every sentence and sends it to human review when it breaks a rule.

Rules:
- Use only the values in the table. Every number you write must be copied exactly from a cell you cite.
- For each sentence, list the cells it uses as `{row, column}` (row = 0-based row index, column = column name).
- Cells with the value "<5" are suppressed for privacy: write "fewer than 5", never a number for them. Empty cells are suppressed rates: don't mention them.
- Describe associations only. Never use causal words: causes, caused, leads to, led to, results in, resulted in, proves, because of, due to.
- No advice, no speculation about why.

Columns: {{columns}}
Rows: {{rows}}
