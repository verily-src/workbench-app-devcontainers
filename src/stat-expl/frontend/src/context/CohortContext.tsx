import { createContext, useContext, useState, ReactNode } from 'react'

interface CohortFilter {
  ageMin?: number
  ageMax?: number
  sex?: 'M' | 'F' | 'all'
  conditions?: string[]
}

interface CohortContextType {
  filters: CohortFilter
  setFilters: (filters: CohortFilter) => void
  flags: string[]
  addFlag: (flag: string) => void
  removeFlag: (flag: string) => void
}

const CohortContext = createContext<CohortContextType | undefined>(undefined)

export function CohortProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<CohortFilter>({ sex: 'all' })
  const [flags, setFlags] = useState<string[]>([])

  const addFlag = (flag: string) => {
    if (!flags.includes(flag)) {
      setFlags([...flags, flag])
    }
  }

  const removeFlag = (flag: string) => {
    setFlags(flags.filter(f => f !== flag))
  }

  return (
    <CohortContext.Provider value={{ filters, setFilters, flags, addFlag, removeFlag }}>
      {children}
    </CohortContext.Provider>
  )
}

export function useCohort() {
  const context = useContext(CohortContext)
  if (!context) {
    throw new Error('useCohort must be used within CohortProvider')
  }
  return context
}
