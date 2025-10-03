# Use snippet 'summarize_a_dataframe' to display summary statistics for a dataframe.
# It assumes snippet 'Setup' has been executed.
# See also https://towardsdatascience.com/exploring-your-data-with-just-1-line-of-python-4b35ce21a82d


## -----[ CHANGE THE DATAFRAME NAME(S) TO MATCH YOURS FROM DATASET BUILDER] -----
YOUR_DATASET_NAME_person_df.loc[:10000,:].profile_report()  # Examine up to the first 10,000 rows. Larger
                                                            # dataframes can be profiled, but it takes more time.
