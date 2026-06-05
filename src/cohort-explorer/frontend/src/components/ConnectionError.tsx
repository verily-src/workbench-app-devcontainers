import { Alert, AlertTitle, Box, Button, Stack } from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import SwapHorizIcon from "@mui/icons-material/SwapHoriz";

interface Props {
  message: string;
  onRetry: () => void;
  onDisconnect: () => void;
}

export default function ConnectionError({ message, onRetry, onDisconnect }: Props) {
  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        flex: 1,
        p: 4,
      }}
    >
      <Alert severity="error" variant="outlined" sx={{ maxWidth: 520 }}>
        <AlertTitle>Unable to load data</AlertTitle>
        {message}
        <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
          <Button
            size="small"
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={onRetry}
          >
            Retry
          </Button>
          <Button
            size="small"
            variant="text"
            startIcon={<SwapHorizIcon />}
            onClick={onDisconnect}
          >
            Change datasource
          </Button>
        </Stack>
      </Alert>
    </Box>
  );
}
