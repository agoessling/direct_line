#include <FreeRTOS.h>
#include <task.h>

void vApplicationGetIdleTaskMemory(StaticTask_t **idle_task_tcb_ptr,
                                   StackType_t **idle_task_stack_ptr,
                                   uint16_t *idle_task_stack_size) {
  static StaticTask_t idle_task_tcb;
  static StackType_t idle_task_stack[configMINIMAL_STACK_SIZE];

  *idle_task_tcb_ptr = &idle_task_tcb;
  *idle_task_stack_ptr = idle_task_stack;
  *idle_task_stack_size = configMINIMAL_STACK_SIZE;
}

void vApplicationGetTimerTaskMemory(StaticTask_t **timer_task_tcb_ptr,
                                    StackType_t **timer_task_stack_ptr,
                                    uint16_t *timer_task_stack_size) {
  static StaticTask_t timer_task_tcb;
  static StackType_t timer_task_stack[configTIMER_TASK_STACK_DEPTH];

  *timer_task_tcb_ptr = &timer_task_tcb;
  *timer_task_stack_ptr = timer_task_stack;
  *timer_task_stack_size = configTIMER_TASK_STACK_DEPTH;
}
