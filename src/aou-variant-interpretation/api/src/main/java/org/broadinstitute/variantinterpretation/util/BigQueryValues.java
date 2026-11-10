package org.broadinstitute.variantinterpretation.util;

import com.google.cloud.bigquery.FieldValue;
import com.google.cloud.bigquery.FieldValueList;
import java.math.BigDecimal;
import java.util.List;
import java.util.stream.Collectors;

/** Null-safe reads of typed column values out of a BigQuery result row. */
public final class BigQueryValues {

  private BigQueryValues() {}

  public static String string(FieldValueList row, String column) {
    FieldValue value = row.get(column);
    return value.isNull() ? null : value.getStringValue();
  }

  public static Double doubleValue(FieldValueList row, String column) {
    FieldValue value = row.get(column);
    return value.isNull() ? null : value.getDoubleValue();
  }

  public static Integer intValue(FieldValueList row, String column) {
    FieldValue value = row.get(column);
    return value.isNull() ? null : (int) value.getLongValue();
  }

  public static List<String> stringList(FieldValueList row, String column) {
    FieldValue value = row.get(column);
    return value.isNull()
        ? List.of()
        : value.getRepeatedValue().stream().map(FieldValue::getStringValue).toList();
  }

  // Collectors.toList() (not Stream.toList()) because an element of a repeated column (e.g.
  // clinvar_rcv_num_stars) can itself be null, and Stream.toList() -- like List.of() -- rejects
  // nulls. (stringList doesn't need this: VatLookupService maps its results through
  // Map.of(...)::get, which throws on a null key.)
  public static List<Integer> intList(FieldValueList row, String column) {
    FieldValue value = row.get(column);
    return value.isNull()
        ? List.of()
        : value.getRepeatedValue().stream()
            .map(v -> v.isNull() ? null : (int) v.getLongValue())
            .collect(Collectors.toList());
  }

  public static BigDecimal bigDecimal(Double value) {
    return value == null ? null : BigDecimal.valueOf(value);
  }
}
