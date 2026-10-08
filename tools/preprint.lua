-- Preprint build (make preprint). paper.md is written for Forgejo; this filter turns it into an
-- article:
--   * drops the Markdown title and author line (the title block comes from tools/preprint.yaml);
--   * moves the "Abstract" section into the abstract metadata (LaTeX abstract environment);
--   * merges each figure or table with the italic "*Figure N. …*" / "*Table N. …*" paragraph that
--     follows it into a real caption, letting LaTeX number it (the paper numbers by order of
--     appearance, so the numbers agree);
--   * swaps figures/<name>.png for the vector dist/fig/<name>.pdf when it exists.

local function caption_of(block, word)
  -- block is a Para whose only content is Emph{ "Word", " ", "N.", " ", ... }; returns the inlines
  -- after the number, or nil
  if block == nil or block.t ~= "Para" or #block.content ~= 1 or block.content[1].t ~= "Emph" then
    return nil
  end
  local inl = block.content[1].content
  if #inl < 4 or inl[1].t ~= "Str" or inl[1].text ~= word or inl[3].t ~= "Str"
     or not inl[3].text:match("^%d+%.$") then
    return nil
  end
  local rest = pandoc.List()
  for i = 5, #inl do rest:insert(inl[i]) end
  return rest
end

local function vector(src)
  local name = src:match("^figures/(.+)%.png$")
  if name then
    local pdf = "dist/fig/" .. name .. ".pdf"
    local f = io.open(pdf, "r")
    if f then f:close(); return pdf end
  end
  return src
end

function Image(el)
  el.src = vector(el.src)
  return el
end

function Pandoc(doc)
  local out, blocks = pandoc.List(), doc.blocks
  local i, title_dropped, author_dropped = 1, false, false
  while i <= #blocks do
    local b = blocks[i]
    if not title_dropped and b.t == "Header" and b.level == 1 then
      title_dropped = true
    elseif title_dropped and not author_dropped and b.t == "Para" and pandoc.utils.stringify(b):find("@") then
      author_dropped = true
    elseif b.t == "Header" and pandoc.utils.stringify(b) == "Abstract" then
      local abs = pandoc.List()
      i = i + 1
      while i <= #blocks and not (blocks[i].t == "Header" and blocks[i].level <= 2) do
        abs:insert(blocks[i]); i = i + 1
      end
      doc.meta.abstract = pandoc.MetaBlocks(abs)
      i = i - 1
    elseif b.t == "Figure" then
      local cap = caption_of(blocks[i + 1], "Figure")
      if cap then
        b.caption = { long = { pandoc.Plain(cap) } }
        i = i + 1
      end
      out:insert(b)
    elseif b.t == "Para" and #b.content == 1 and b.content[1].t == "Image" then
      local cap = caption_of(blocks[i + 1], "Figure")
      if cap then
        local img = b.content[1]
        out:insert(pandoc.Figure(pandoc.Plain({ img }), { long = { pandoc.Plain(cap) } }))
        i = i + 1
      else
        out:insert(b)
      end
    elseif b.t == "Table" then
      local cap = caption_of(blocks[i + 1], "Table")
      if cap then
        b.caption = { long = { pandoc.Plain(cap) } }
        i = i + 1
      end
      out:insert(b)
    else
      out:insert(b)
    end
    i = i + 1
  end
  doc.blocks = out
  return doc
end
