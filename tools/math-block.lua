-- Render ```math fenced blocks (Forgejo/GitHub display math) as LaTeX display math in pandoc,
-- and replace ```mermaid blocks with the PNG rendered by tools/mermaid2png.py (keyed by a hash of
-- the block, so an edited diagram that was not re-rendered fails the build).
function CodeBlock(el)
  if el.classes:includes("math") then
    return pandoc.Para({ pandoc.Math("DisplayMath", el.text) })
  end
  if el.classes:includes("mermaid") then
    local path = "figures/fig_mermaid_" .. pandoc.utils.sha1(el.text .. "\n"):sub(1, 8) .. ".png"
    local f = io.open(path, "r")
    if not f then
      error("missing " .. path .. "; run: uv run python tools/mermaid2png.py")
    end
    f:close()
    return pandoc.Para({ pandoc.Image({}, path) })
  end
end
