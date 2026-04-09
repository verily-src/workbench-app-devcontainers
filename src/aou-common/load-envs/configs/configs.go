package configs

import _ "embed"

//go:embed datacollection_mapping.json
var DatacollectionMapping []byte

//go:embed cdr_config_test.json
var CdrConfigTest []byte

//go:embed cdr_config_stable.json
var CdrConfigStable []byte

//go:embed cdr_config_prod.json
var CdrConfigProd []byte
