# WoSB Workbench 4.3.9

- Fixed "ValueError: Too many report entries" when auditing a large Reports folder or ZIP. The audit now
  indexes only report files (.json/.jsonl/.csv/.md/.txt) and skips extracted asset trees, so XNB, PNG and
  audio output alongside the reports no longer counts toward the 80,000-file safety limit.
