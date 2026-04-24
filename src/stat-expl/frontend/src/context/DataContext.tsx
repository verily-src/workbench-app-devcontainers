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

  useEffect(() => {
    // Fetch all summary data once on app load
    const fetchAllData = async () => {
      setIsLoading(true)
      try {
        // Fetch in parallel for speed
        const [
          healthRes,
          datasetsRes,
          demographicsRes,
          variablesRes,
          diagnosesRes,
          timelineRes,
          sensorRes,
          qualityRes
        ] = await Promise.all([
          fetch('/dashboard/api/health'),
          fetch('/dashboard/api/datasets'),
          fetch('/dashboard/api/demographics'),
          fetch('/dashboard/api/variables/all'),
          fetch('/dashboard/api/diagnoses'),
          fetch('/dashboard/api/enrollment-timeline'),
          fetch('/dashboard/api/sensordata'),
          fetch('/dashboard/api/quality')
        ])

        const [
          healthData,
          datasetsData,
          demographicsData,
          variablesData,
          diagnosesData,
          timelineData,
          sensorDataData,
          qualityData
        ] = await Promise.all([
          healthRes.json(),
          datasetsRes.json(),
          demographicsRes.json(),
          variablesRes.json(),
          diagnosesRes.json(),
          timelineRes.json(),
          sensorRes.json(),
          qualityRes.json()
        ])

        setApiStatus(healthData.status)
        setDatasets(datasetsData)
        setDemographics(demographicsData)
        setVariables(variablesData.variables)
        setDiagnoses(diagnosesData.conditions)
        setTimeline(timelineData.timeline)
        setSensorData(sensorDataData)
        setQuality(qualityData)
      } catch (error) {
        console.error('Failed to fetch data:', error)
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
