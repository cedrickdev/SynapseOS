import { commandNavigationItems, type NavigationItem } from '../../config/navigation'

export function searchNavigation(query: string, limit = 8): readonly NavigationItem[] {
  const boundedLimit = Math.max(1, Math.min(limit, 20))
  const normalizedQuery = query.trim().toLocaleLowerCase('en-US')

  if (!normalizedQuery) {
    return commandNavigationItems.slice(0, boundedLimit)
  }

  const terms = normalizedQuery.split(/\s+/u)
  return commandNavigationItems
    .filter((item) => {
      const searchable = `${item.label} ${item.description}`.toLocaleLowerCase('en-US')
      return terms.every(term => searchable.includes(term))
    })
    .slice(0, boundedLimit)
}
