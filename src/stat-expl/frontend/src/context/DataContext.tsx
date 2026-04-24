import { createContext, useContext, useState, useEffect, ReactNode } from 'react'

interface DatasetInfo {
  project: string
  datasets: { name: string; table_count: number }[]
  total_tables: number
}

interface Demographics {
  total_participants: number
  mean_age: number
  min_age: number
  max_age: number
  male_count: number
  female_count: number
  age_distribution: { age_group: string; count: number }[]
  enrollment_start: string
  enrollment_end: string
}

interface Variable {
  name: string
  type: string
  description: string
  category: string
  completeness: number
  range: string
}

interface Condition {
  name: string
  code: string
  count: number
  percentage: number
}

interface TimelinePoint {
  month: string
  count: number
}

interface SensorData {
  participants_with_step_data: number
  total_step_records: number
  total_pulse_records: number
  total_sleep_records: number
  data_coverage_pct: number
}

interface QualityData {
  overall_score: number
  issues: { issue: string; severity: string; affected: number; percentage: number }[]
  high_severity_count: number
  medium_severity_count: number
  low_severity_count: number
}

interface DataContextType {
  // Static cached data (fetched once)
  datasets: DatasetInfo | null
  demographics: Demographics | null
  variables: Variable[]
  diagnoses: Condition[]
  timeline: TimelinePoint[]
  sensorData: SensorData | null
  quality: QualityData | null

  // Loading state
  isLoading: boolean
  loadingProgress: { [key: string]: 'pending' | 'loading' | 'complete' | 'error' }
  loadingMessage: string

  // Health check
  apiStatus: string | null
}

const DataContext = createContext<DataContextType | undefined>(undefined)

export function DataProvider({ children }: { children: ReactNode }) {
  const [datasets, setDatasets] = useState<DatasetInfo | null>(null)
  const [demographics, setDemographics] = useState<Demographics | null>(null)
  const [variables, setVariables] = useState<Variable[]>([])
  const [diagnoses, setDiagnoses] = useState<Condition[]>([])
  const [timeline, setTimeline] = useState<TimelinePoint[]>([])
  const [sensorData, setSensorData] = useState<SensorData | null>(null)
  const [quality, setQuality] = useState<QualityData | null>(null)
  const [apiStatus, setApiStatus] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadingProgress, setLoadingProgress] = useState<{ [key: string]: 'pending' | 'loading' | 'complete' | 'error' }>({})
  const [loadingMessage, setLoadingMessage] = useState('Initializing...')

  useEffect(() => {
    // Fetch with timeout wrapper
    const fetchWithTimeout = async (url: string, timeout = 30000) => {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), timeout)
      try {
        const response = await fetch(url, { signal: controller.signal })
        clearTimeout(timeoutId)
        return response
      } catch (error) {
        clearTimeout(timeoutId)
        throw error
      }
    }

    // Fetch all summary data once on app load
    const fetchAllData = async () => {
      setIsLoading(true)

      const endpoints = {
        health: '/dashboard/api/health',
        datasets: '/dashboard/api/datasets',
        demographics: '/dashboard/api/demographics',
        variables: '/dashboard/api/variables/all',
        diagnoses: '/dashboard/api/diagnoses',
        timeline: '/dashboard/api/enrollment-timeline',
        sensordata: '/dashboard/api/sensordata',
        quality: '/dashboard/api/quality'
      }

      // Initialize progress tracking
      const initialProgress = Object.keys(endpoints).reduce((acc, key) => ({
        ...acc,
        [key]: 'pending' as const
      }), {})
      setLoadingProgress(initialProgress)

      try {
        // Fetch in parallel with individual error handling
        const results = await Promise.allSettled(
          Object.entries(endpoints).map(async ([key, url]) => {
            setLoadingProgress(prev => ({ ...prev, [key]: 'loading' }))
            setLoadingMessage(`Loading ${key}...`)
            try {
              const response = await fetchWithTimeout(url)
              if (!response.ok) throw new Error(`HTTP ${response.status}`)
              const data = await response.json()
              setLoadingProgress(prev => ({ ...prev, [key]: 'complete' }))
              return { key, data, success: true }
            } catch (error) {
              console.error(`Failed to fetch ${key}:`, error)
              setLoadingProgress(prev => ({ ...prev, [key]: 'error' }))
              return { key, error, success: false }
            }
          })
        )

        // Process successful results (graceful degradation)
        results.forEach((result) => {
          if (result.status === 'fulfilled' && result.value.success) {
            const { key, data } = result.value
            switch (key) {
              case 'health':
                setApiStatus(data.status)
                break
              case 'datasets':
                setDatasets(data)
                break
              case 'demographics':
                setDemographics(data)
                break
              case 'variables':
                setVariables(data.variables || [])
                break
              case 'diagnoses':
                setDiagnoses(data.conditions || [])
                break
              case 'timeline':
                setTimeline(data.timeline || [])
                break
              case 'sensordata':
                setSensorData(data)
                break
              case 'quality':
                setQuality(data)
                break
            }
          }
        })

        setLoadingMessage('Complete!')
      } catch (error) {
        console.error('Failed to fetch data:', error)
        setLoadingMessage('Error loading data')
      } finally {
        setIsLoading(false)
      }
    }

    fetchAllData()
  }, []) // Only fetch once on mount

  return (
    <DataContext.Provider
      value={{
        datasets,
        demographics,
        variables,
        diagnoses,
        timeline,
        sensorData,
        quality,
        isLoading,
        loadingProgress,
        loadingMessage,
        apiStatus
      }}
    >
      {children}
    </DataContext.Provider>
  )
}

export function useData() {
  const context = useContext(DataContext)
  if (!context) {
    throw new Error('useData must be used within DataProvider')
  }
  return context
}
