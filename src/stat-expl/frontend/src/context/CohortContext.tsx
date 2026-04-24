import { createContext, useContext, useState, ReactNode } from 'react';

// Filter types
export interface CohortFilter {
  id: string;
  variable: string;
  operator: 'eq' | 'neq' | 'gt' | 'lt' | 'gte' | 'lte' | 'between' | 'in';
  value: string | number | [number, number] | string[];
  label: string; // Human-readable label for display
}

// Flag types
export type FlagSeverity = 'red' | 'amber' | 'green';

export interface Flag {
  id: string;
  severity: FlagSeverity;
  message: string;
  source: string; // Which page/computation generated this flag
  dismissed: boolean;
  annotation?: string; // User notes on the flag
}

// Variable tagging (for Hypotheses page)
export interface VariableTag {
  columnName: string;
  dataset: string;
  table: string;
  tags: ('endpoint' | 'exposure' | 'confounder')[];
}

interface CohortContextType {
  // Filters
  filters: CohortFilter[];
  addFilter: (filter: CohortFilter) => void;
  removeFilter: (filterId: string) => void;
  clearFilters: () => void;

  // Patient count (computed from filters)
  patientCount: number;
  setPatientCount: (count: number) => void;

  // Flags
  flags: Flag[];
  addFlag: (flag: Omit<Flag, 'id' | 'dismissed'>) => void;
  removeFlag: (flagId: string) => void;
  dismissFlag: (flagId: string) => void;
  annotateFlag: (flagId: string, annotation: string) => void;
  clearFlags: () => void;

  // Variable tags
  variableTags: VariableTag[];
  tagVariable: (columnName: string, dataset: string, table: string, tag: 'endpoint' | 'exposure' | 'confounder') => void;
  untagVariable: (columnName: string, dataset: string, table: string, tag: 'endpoint' | 'exposure' | 'confounder') => void;
  getVariableTags: (columnName: string, dataset: string, table: string) => ('endpoint' | 'exposure' | 'confounder')[];
}

const CohortContext = createContext<CohortContextType | undefined>(undefined);

export function useCohort() {
  const context = useContext(CohortContext);
  if (!context) {
    throw new Error('useCohort must be used within CohortProvider');
  }
  return context;
}

interface CohortProviderProps {
  children: ReactNode;
}

export function CohortProvider({ children }: CohortProviderProps) {
  const [filters, setFilters] = useState<CohortFilter[]>([]);
  const [patientCount, setPatientCount] = useState<number>(0);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [variableTags, setVariableTags] = useState<VariableTag[]>([]);

  // Filter operations
  const addFilter = (filter: CohortFilter) => {
    setFilters(prev => [...prev, filter]);
  };

  const removeFilter = (filterId: string) => {
    setFilters(prev => prev.filter(f => f.id !== filterId));
  };

  const clearFilters = () => {
    setFilters([]);
  };

  // Flag operations
  const addFlag = (flag: Omit<Flag, 'id' | 'dismissed'>) => {
    const newFlag: Flag = {
      ...flag,
      id: `flag-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      dismissed: false
    };
    setFlags(prev => [...prev, newFlag]);
  };

  const removeFlag = (flagId: string) => {
    setFlags(prev => prev.filter(f => f.id !== flagId));
  };

  const dismissFlag = (flagId: string) => {
    setFlags(prev => prev.map(f =>
      f.id === flagId ? { ...f, dismissed: true } : f
    ));
  };

  const annotateFlag = (flagId: string, annotation: string) => {
    setFlags(prev => prev.map(f =>
      f.id === flagId ? { ...f, annotation } : f
    ));
  };

  const clearFlags = () => {
    setFlags([]);
  };

  // Variable tagging operations
  const tagVariable = (columnName: string, dataset: string, table: string, tag: 'endpoint' | 'exposure' | 'confounder') => {
    setVariableTags(prev => {
      const existing = prev.find(
        vt => vt.columnName === columnName && vt.dataset === dataset && vt.table === table
      );

      if (existing) {
        if (!existing.tags.includes(tag)) {
          return prev.map(vt =>
            vt.columnName === columnName && vt.dataset === dataset && vt.table === table
              ? { ...vt, tags: [...vt.tags, tag] }
              : vt
          );
        }
        return prev;
      }

      return [...prev, { columnName, dataset, table, tags: [tag] }];
    });
  };

  const untagVariable = (columnName: string, dataset: string, table: string, tag: 'endpoint' | 'exposure' | 'confounder') => {
    setVariableTags(prev => {
      return prev.map(vt =>
        vt.columnName === columnName && vt.dataset === dataset && vt.table === table
          ? { ...vt, tags: vt.tags.filter(t => t !== tag) }
          : vt
      ).filter(vt => vt.tags.length > 0);
    });
  };

  const getVariableTags = (columnName: string, dataset: string, table: string): ('endpoint' | 'exposure' | 'confounder')[] => {
    const vt = variableTags.find(
      vt => vt.columnName === columnName && vt.dataset === dataset && vt.table === table
    );
    return vt?.tags || [];
  };

  const value: CohortContextType = {
    filters,
    addFilter,
    removeFilter,
    clearFilters,
    patientCount,
    setPatientCount,
    flags,
    addFlag,
    removeFlag,
    dismissFlag,
    annotateFlag,
    clearFlags,
    variableTags,
    tagVariable,
    untagVariable,
    getVariableTags
  };

  return (
    <CohortContext.Provider value={value}>
      {children}
    </CohortContext.Provider>
  );
}
