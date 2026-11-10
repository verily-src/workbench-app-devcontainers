import * as Style from "../../libs/style";

/** No value for this cell: the variant isn't present in the source behind it. */
export default function NotAvailable() {
  return <span style={Style.elements.notAvailable}>—</span>;
}
