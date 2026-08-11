package com.boyaa.antwarsId;

/* JADX INFO: loaded from: classes.dex */
public class DispatcherEventCenter {
    public static final String MIMOPAY_RESULT = "mimopay_result";

    public static void dispathEventToActionScript(String eventName, String value) {
        AntExtension.context.dispatchStatusEventAsync(eventName, value);
    }
}
