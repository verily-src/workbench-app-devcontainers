nextflow.enable.dsl = 2

def shellQuote(value) {
    "'${value.toString().replace("'", "'\\''")}'"
}

process SUMMARIZE_VARIANT {
    tag "${variant_id}"
    container params.container
    publishDir params.publish_dir ?: params.output_uri_prefix, mode: 'copy', overwrite: false

    input:
    path input_csv, name: 'analysis_input.csv'
    path variant_dictionary, name: 'input_dictionary.csv'
    path analysis_script
    path vendor_archive
    val variant_id
    val cohort_size
    val input_uri
    val dictionary_uri
    val output_uri_prefix
    val source_resource
    val source_tables
    val workflow_id
    val run_id
    val use_vendored_pydantic

    output:
    path 'carrier_summary.csv', emit: summary
    path 'variant_dictionary.csv', emit: dictionary
    path 'run_manifest.json', emit: manifest

    script:
    def cli = ['--input', input_csv, '--variant-dictionary', variant_dictionary,
               '--output-dir', '.', '--variant-id', variant_id,
               '--input-uri', input_uri, '--output-uri-prefix', output_uri_prefix]
    cli += ['--variant-dictionary-uri', dictionary_uri]
    if (cohort_size) cli += ['--cohort-size', cohort_size]
    if (source_resource) cli += ['--source-resource', source_resource]
    for (table in source_tables) cli += ['--source-table', table]
    if (workflow_id) cli += ['--workflow-id', workflow_id]
    if (run_id) cli += ['--run-id', run_id]
    def args = cli.collect { shellQuote(it) }.join(' ')
    def pythonEnv = use_vendored_pydantic ? "PYTHONPATH=${shellQuote('vendor_runtime')} " : ''
    """
    ${shellQuote(params.python)} -m zipfile -e ${shellQuote(vendor_archive)} vendor_runtime
    ${pythonEnv}${shellQuote(params.python)} -c 'import pydantic; assert int(pydantic.__version__.split(".")[0]) >= 2'
    ${pythonEnv}${shellQuote(params.python)} ${shellQuote(analysis_script)} ${args}
    """
}

workflow {
    if (!params.input) error 'Set --input to one staged CSV or S3 object.'

    def dictionaryPath = params.variant_dictionary ?: "${projectDir}/variant_dictionary.csv"
    def vendorPath = params.vendor_archive ?: "${projectDir}/vendor.zip"
    def outputPrefix = params.output_bucket && params.output_key
        ? "s3://${params.output_bucket}/${params.output_key}"
        : (params.output_uri_prefix ?: 'results')
    if (['*', '?', '['].any { params.input.contains(it) }) {
        error 'Set --input to one CSV object, not a glob.'
    }
    if (['*', '?', '['].any { dictionaryPath.contains(it) }) {
        error 'Set --variant_dictionary to one dictionary object, not a glob.'
    }
    if (params.require_s3_output && !outputPrefix.startsWith('s3://')) {
        error 'The HealthOmics profile requires an S3 output URI prefix.'
    }
    def sourceTables = params.source_tables
    if (sourceTables instanceof String) {
        sourceTables = sourceTables.split(',').collect { it.trim() }.findAll { it }
    }
    sourceTables = sourceTables ?: []

    def inputUri = params.input_uri ?: params.input
    def cohortSize = params.cohort_size == null ? '' : params.cohort_size.toString()
    if (params.require_s3_output && !params.input.startsWith('s3://')) {
        error 'The HealthOmics profile requires an S3 input CSV.'
    }
    def inputs = Channel.fromPath(params.input, checkIfExists: true)
        .ifEmpty { error "Input CSV not found: ${params.input}" }
    def dictionary = Channel.fromPath(dictionaryPath, checkIfExists: true)
        .ifEmpty { error "Variant dictionary not found: ${dictionaryPath}" }
    def scriptFile = Channel.value(file("${projectDir}/analysis.py"))
    def vendor = Channel.value(file(vendorPath))
    SUMMARIZE_VARIANT(
        inputs,
        dictionary,
        scriptFile,
        vendor,
        params.variant_id ?: 'SYN_VAR_0021',
        cohortSize,
        inputUri,
        params.variant_dictionary_uri ?: dictionaryPath,
        outputPrefix,
        params.source_resource ?: '',
        sourceTables,
        params.workflow_id ?: '',
        params.run_id ?: '',
        params.use_vendored_pydantic,
    )
}
