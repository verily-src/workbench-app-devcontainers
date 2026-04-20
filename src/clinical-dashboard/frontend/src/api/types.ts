export interface CohortFilters {
  sex?: string
  min_age?: number
  max_age?: number
  disease?: string
  medication?: string
}

export interface Participant {
  usubjid: string
  sex: string
  age_at_enrollment: number
}

export interface CohortResponse {
  cohort_id: string
  filters: CohortFilters
  total_participants: number
  participants: Participant[]
}

export interface DeviceMetricPoint {
  study_day: number
  mean: number
  std: number
  count: number
}

export interface DeviceDataResponse {
  cohort_size: number
  metrics: {
    steps?: DeviceMetricPoint[]
    sleep?: DeviceMetricPoint[]
    sleep_rem?: DeviceMetricPoint[]
    sleep_deep?: DeviceMetricPoint[]
    sleep_light?: DeviceMetricPoint[]
    hrv?: DeviceMetricPoint[]
    walking_bouts?: DeviceMetricPoint[]
    nonwalking_bouts?: DeviceMetricPoint[]
  }
}

export interface IndividualDataPoint {
  study_day: number
  value: number
}

export interface IndividualDataResponse {
  usubjid: string
  metrics: {
    steps?: IndividualDataPoint[]
    sleep?: IndividualDataPoint[]
    sleep_rem?: IndividualDataPoint[]
    sleep_deep?: IndividualDataPoint[]
    sleep_light?: IndividualDataPoint[]
    hrv?: IndividualDataPoint[]
  }
}

export interface VisitScatter {
  usubjid: string
  visit_num: number
  visit_name: string
  study_day: number
}

export interface VisitScatterResponse {
  cohort_size: number
  visits: VisitScatter[]
}

export interface VisitPoint {
  visit_num: number
  visit_name: string
  sbp_mean: number
  sbp_std: number
  dbp_mean: number
  dbp_std: number
  hr_mean: number
  hr_std: number
  count: number
}

export interface ClinicalTimelineResponse {
  cohort_size: number
  visits: VisitPoint[]
}
