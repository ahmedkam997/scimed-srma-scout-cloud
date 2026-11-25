"""Apply the tested fixed-line patch to the exact pinned upstream source.
Fail if upstream code differs; no silent partial patch or false empty page.
"""
from pathlib import Path
import sys

def patch(source):
    replacements={
        "line: page,":"line: 1,",
        "const pageEntry = Array.isArray(response) ? response[page - 1] : undefined;":
        """const pageEntry = Array.isArray(response) && response.length === 1 ? response[0] : undefined;
  const payload = getObject(pageEntry)?.retvals?.hits;
  const total = payload?.total;
  if (!Number.isInteger(total?.value) || total.value < 0 || !Array.isArray(payload?.hits)
      || (total.relation !== undefined && total.relation !== "eq")
      || (getObject(pageEntry)?.linenumber !== undefined && getObject(pageEntry)?.linenumber !== 1)
      || (payload.hits.length === 0 && total.value > (page - 1) * pageSize)
      || payload.hits.length > pageSize
      || (total.value === 0 && payload.hits.length > 0)) {
    throw new Error("PROSPERO malformed or incomplete search response");
  }""",
    }
    for old,new in replacements.items():
        if source.count(old)!=1:raise ValueError("Pinned upstream patch anchor missing or ambiguous: "+old)
        source=source.replace(old,new)
    return source

if __name__=="__main__":
    p=Path(sys.argv[1]);p.write_text(patch(p.read_text()))
