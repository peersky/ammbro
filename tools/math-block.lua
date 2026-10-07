-- Render ```math fenced blocks (Forgejo/GitHub display math) as LaTeX display math in pandoc.
function CodeBlock(el)
  if el.classes:includes("math") then
    return pandoc.Para({ pandoc.Math("DisplayMath", el.text) })
  end
end
