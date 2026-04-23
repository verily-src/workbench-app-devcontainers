import { useEffect, useState } from 'react';
import { useCohort } from '../context/CohortContext';
import { loadSchema, Schema } from '../lib/schema';

export function TestPage() {
  const [schema, setSchema] = useState<Schema | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const cohort = useCohort();

  useEffect(() => {
    loadSchema()
      .then(data => {
        setSchema(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  const testContextAccess = () => {
    cohort.addFilter({
      id: 'test-filter-1',
      variable: 'age',
      operator: 'gte',
      value: 18,
      label: 'Age ≥ 18'
    });

    cohort.addFlag({
      severity: 'amber',
      message: 'Test flag from test page',
      source: 'TestPage'
    });

    cohort.setPatientCount(12847);
  };

  if (loading) {
    return <div className="p-8">Loading schema...</div>;
  }

  if (error) {
    return <div className="p-8 text-red-600">Error: {error}</div>;
  }

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold mb-4">Phase 1 Test Page</h2>

      <div className="space-y-6">
        {/* Schema Test */}
        <div className="bg-white p-4 rounded shadow">
          <h3 className="text-lg font-semibold mb-2">Schema Loaded Successfully ✓</h3>
          <div className="text-sm space-y-1">
            <p>Data Project: {schema?.data_project}</p>
            <p>App Project: {schema?.app_project}</p>
            <p>Extracted At: {schema?.extracted_at}</p>
            <p>Datasets: {schema?.datasets.length}</p>
            <p>
              Total Tables: {schema?.datasets.reduce((sum, ds) => sum + ds.tables.length, 0)}
            </p>
            <p>
              Total Columns: {schema?.datasets.reduce(
                (sum, ds) => sum + ds.tables.reduce((tsum, t) => tsum + t.columns.length, 0),
                0
              )}
            </p>
          </div>
        </div>

        {/* Context Test */}
        <div className="bg-white p-4 rounded shadow">
          <h3 className="text-lg font-semibold mb-2">Context Access Test</h3>
          <button
            onClick={testContextAccess}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            Add Test Filter & Flag
          </button>
          <div className="mt-4 text-sm space-y-1">
            <p>Active Filters: {cohort.filters.length}</p>
            <p>Active Flags: {cohort.flags.filter(f => !f.dismissed).length}</p>
            <p>Patient Count: {cohort.patientCount.toLocaleString()}</p>
            {cohort.filters.length > 0 && (
              <div className="mt-2">
                <p className="font-semibold">Filters:</p>
                <ul className="list-disc list-inside">
                  {cohort.filters.map(f => (
                    <li key={f.id}>{f.label}</li>
                  ))}
                </ul>
              </div>
            )}
            {cohort.flags.length > 0 && (
              <div className="mt-2">
                <p className="font-semibold">Flags:</p>
                <ul className="list-disc list-inside">
                  {cohort.flags.map(f => (
                    <li key={f.id} className={`text-${f.severity === 'red' ? 'red' : f.severity === 'amber' ? 'yellow' : 'green'}-600`}>
                      [{f.severity.toUpperCase()}] {f.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
