-- Preprint build: the title block comes from tools/preprint.yaml, so drop the Markdown title (first
-- level-1 header) and the author line that follows it.
local dropped_title, dropped_author = false, false
function Header(el)
  if not dropped_title and el.level == 1 then
    dropped_title = true
    return {}
  end
end
function Para(el)
  if dropped_title and not dropped_author then
    local text = pandoc.utils.stringify(el)
    if text:find("@") then
      dropped_author = true
      return {}
    end
  end
end
